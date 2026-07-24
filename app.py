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

HISTORY_FILE = "history.json"

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return []

def save_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    
def add_history_entry(url, title, uploader, file_path, platform):
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

whisper_model = None
def get_whisper():
    global whisper_model
    if whisper_model is None:
        import whisper
        print("Loading Whisper model (this may take a moment)...")
        whisper_model = whisper.load_model("base")
    return whisper_model

# Cache the face detection cascade globally but initialize lazily
_face_cascade = None

def get_face_center_x(video_path):
    import cv2
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Only reframe if it's horizontal
    if width <= height:
        cap.release()
        return None
        
    face_cascade = _face_cascade
    centers = []
    frame_count = 0
    
    # Read every 15th frame, max 10 seconds (approx 300 frames)
    while cap.isOpened() and frame_count < 300:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_count % 15 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Resize for faster processing
            small = cv2.resize(gray, (0,0), fx=0.5, fy=0.5)
            faces = face_cascade.detectMultiScale(small, 1.1, 4)
            for (x, y, w, h) in faces:
                centers.append((x + w//2) * 2)
                break
        frame_count += 1
        
    cap.release()
    if centers:
        return sum(centers) // len(centers)
    return None

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

def shazam_file(audio_path):
    async def recognize():
        shazam = Shazam()
        return await shazam.recognize(audio_path)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(recognize())
    except Exception as e:
        print("Shazam error:", e)
        return None
    finally:
        loop.close()

@app.route('/')
def index():
    return render_template('index.html')


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
    trim_start = request.form.get('trimStart')
    trim_end = request.form.get('trimEnd')
    
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
                        q.put({"status": f"{prefix}Analyzing face position for Smart Auto-Crop..."})
                        center_x = get_face_center_x(input_path)
                        if center_x is not None:
                            vf_filters.append(f"crop=ih*9/16:ih:{center_x}-ih*9/32:0")
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

                    # 2. File Size & Resolution Scaling (MB Reduction)
                    compress_opt = request.form.get('compress')
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
                        elif compress_opt == "compress_web":
                            crf_val = "32" # ~75% MB size reduction (Web/Discord)
                    
                    # Audio formats (ignore video filters)
                    if format_opt in ["mp3", "wav"]:
                        if format_opt == "mp3":
                            cmd.extend(["-vn", "-acodec", "libmp3lame", "-q:a", "2"])
                        else:
                            cmd.extend(["-vn", "-acodec", "pcm_s16le"])
                    else:
                        # Video or Image formats
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
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    # Cleanup temp for this file immediately
                    try: os.remove(input_path) 
                    except Exception: pass
                    
                except Exception as e:
                    failed_count += 1
                    err_msg = str(e)
                    q.put({"status": f"{prefix}Error converting file."})
                    time.sleep(3)
                    
            if failed_count == 0:
                q.put({"status": f"Successfully saved to {output_dir}", "done": True})
            else:
                q.put({"status": f"Complete! ({failed_count} failed)", "done": True})

        t = threading.Thread(target=run_conv)
        t.start()
        
        while True:
            msg = q.get()
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

    url = urls_raw.strip()
    urls = [url] if url else []

    if not urls:
        return jsonify({"error": "URL is required"}), 400
        
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
                # Clean up ANSI escape sequences from percent
                percent = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', percent)
                q.put({"status": f"Downloading: {percent}"})
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
                            if os.path.exists(final_path) and processing_options.get('enableThumbnail', True):
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
                                
                                # Audio Recognition & Metadata
                                if processing_options.get('enableSongMeta', True):
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
                                if processing_options.get('enableTranscription', True):
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
                                            with open(transcript_path, "w", encoding="utf-8") as f:
                                                f.write(result.get("text", "").strip())
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

        t = threading.Thread(target=run_dl)
        t.start()

        while True:
            msg = q.get()
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("done") or msg.get("error") or msg.get("action_required"):
                break

    return Response(generate(), mimetype='text/event-stream')




@app.route('/api/gallery', methods=['GET'])
def list_gallery():
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
    return jsonify(media)

@app.route('/api/media/<folder>/<path:filename>')
def serve_media(folder, filename):
    base_dir = os.path.join(os.path.expanduser("~"), "Documents", "Media Grabber")
    safe_folder = os.path.basename(folder)
    return send_from_directory(os.path.join(base_dir, safe_folder), filename)

@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    path = request.json.get('path')
    if not path or not os.path.exists(path):
        return jsonify({"error": "Path not found"}), 400
    
    if os.path.isfile(path):
        subprocess.run(['explorer', '/select,', os.path.abspath(path)])
    else:
        os.startfile(os.path.abspath(path))
    return jsonify({"success": True})

@app.route('/api/preview')
def preview_file():
    # send_file is imported at the top of the file
    path = request.args.get('path')
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return "Not found", 404
    return send_file(path)

@app.route('/api/batch_clean', methods=['POST'])
def batch_clean():
    data = request.json
    target_dirs = data.get('target_dirs', [])
    
    output_dir = os.path.join(DEFAULT_SAVE_DIR, "AI Cleaned")
    
    try:
        from cleaner import run_batch_cleaner
        return Response(run_batch_cleaner(target_dirs, output_dir, is_upload=False), mimetype='text/event-stream')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/batch_clean_upload', methods=['POST'])
def batch_clean_upload():
    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded"}), 400
        
    files = request.files.getlist('files')
    if not files or not files[0].filename:
        return jsonify({"error": "No selected files"}), 400
        
    import time
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
        return Response(run_batch_cleaner(uploaded_paths, upload_folder, is_upload=True), mimetype='text/event-stream')
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
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
        
    try:
        from send2trash import send2trash
        send2trash(path)
    except Exception:
        try:
            os.remove(path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    return jsonify({"success": True})

if __name__ == '__main__':
    import webbrowser
    import threading
    from waitress import serve
    print("Server running on http://127.0.0.1:5000")
    # Launch browser precisely after the server is ready
    threading.Timer(1.25, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    serve(app, host='127.0.0.1', port=5000, threads=8)
