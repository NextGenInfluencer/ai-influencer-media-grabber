import gradio as gr
import os
import re
import sys
import subprocess
import threading
import uuid
import json
import time
import asyncio
import tempfile
import shutil
from pathlib import Path
import spaces

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from shazamio import Shazam
except ImportError:
    Shazam = None

if imageio_ffmpeg:
    os.environ["PATH"] += os.pathsep + os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())

whisper_model = None
def get_whisper():
    global whisper_model
    if whisper_model is None:
        try:
            import whisper
            print("Loading Whisper model (this may take a moment)...")
            whisper_model = whisper.load_model("base")
        except Exception as e:
            print(f"Failed to load whisper: {e}")
    return whisper_model

def shazam_file(audio_path):
    if not Shazam:
        return None
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

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

_face_cascade = None
def get_face_center_x(video_path):
    try:
        import cv2
    except ImportError:
        return None
    global _face_cascade
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened(): return None
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    if width <= height:
        cap.release()
        return None
        
    centers = []
    frame_count = 0
    
    while cap.isOpened() and frame_count < 300:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_count % 15 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (0,0), fx=0.5, fy=0.5)
            faces = _face_cascade.detectMultiScale(small, 1.1, 4)
            for (x, y, w, h) in faces:
                centers.append((x + w//2) * 2)
                break
        frame_count += 1
        
    cap.release()
    if centers:
        return sum(centers) // len(centers)
    return None

WEB_DOWNLOADS_DIR = os.path.join(os.getcwd(), "web_downloads")
os.makedirs(WEB_DOWNLOADS_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(WEB_DOWNLOADS_DIR, "history.json")

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return []

def save_history(data):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    except: pass
    
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

def load_history_df():
    import pandas as pd
    from datetime import datetime
    data = load_history()
    if not data:
        return pd.DataFrame(columns=["Time", "Platform", "Title", "Uploader", "URL", "File"])
    
    formatted = []
    for d in data:
        dt = datetime.fromtimestamp(d.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M:%S")
        formatted.append({
            "Time": dt,
            "Platform": d.get("platform", ""),
            "Title": d.get("title", ""),
            "Uploader": d.get("uploader", ""),
            "URL": d.get("url", ""),
            "File": os.path.basename(d.get("file_path", ""))
        })
    return pd.DataFrame(formatted)

def clear_history_fn():
    save_history([])
    return load_history_df()

def cleanup_daemon():
    while True:
        try:
            current_time = time.time()
            for root, dirs, files in os.walk(WEB_DOWNLOADS_DIR):
                for f in files:
                    if f == "history.json": continue
                    file_path = os.path.join(root, f)
                    try:
                        if current_time - os.path.getmtime(file_path) > 3600:
                            os.remove(file_path)
                            print(f"[Cleanup] Deleted {file_path}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"Cleanup error: {e}")
        time.sleep(600)

threading.Thread(target=cleanup_daemon, daemon=True).start()

# --- BACKEND FUNCTIONS ---

@spaces.GPU(duration=120)
def process_download(url, options, custom_name):
    if not yt_dlp:
        yield "Error: yt-dlp is not installed.", None
        return

    url = url.strip()
    if not url:
        yield "Error: No URL provided.", None
        return

    opt_force_h264 = "Force H.264 Encoding" in options
    opt_extract_frame = "Extract First Frame" in options
    opt_extract_prompt = "Extract AI Prompt (BLIP)" in options
    opt_identify_song = "Identify Song Metadata" in options
    opt_transcribe = "Transcribe Audio (Whisper)" in options
    opt_ai_bypass = "AI Bypass (Scramble & Clean)" in options

    yield f"Starting process for: {url}", None
    
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(WEB_DOWNLOADS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    
    filename_template = f'{sanitize_filename(custom_name)}' if custom_name else '%(title)s_%(id)s'
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best' if opt_force_h264 else 'bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'restrictfilenames': True,
        'outtmpl': os.path.join(task_dir, f'{filename_template}.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'retries': 5,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'web']
            }
        }
    }
    
    if imageio_ffmpeg:
        ydl_opts['ffmpeg_location'] = imageio_ffmpeg.get_ffmpeg_exe()

    log_msgs = []
    def log(msg):
        log_msgs.append(msg)
        return "\n".join(log_msgs[-10:])

    final_files_to_return = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            yield log("Fetching metadata and downloading..."), None
            info = ydl.extract_info(url, download=True)
            if not info:
                yield log("Failed. No video found."), None
                return
            
            final_path = None
            if 'requested_downloads' in info and info['requested_downloads']:
                final_path = info['requested_downloads'][0].get('filepath')
            if not final_path:
                final_path = info.get('_filename') or ydl.prepare_filename(info)
                
            if final_path:
                base, _ = os.path.splitext(final_path)
                if not os.path.exists(final_path) and os.path.exists(base + ".mp4"):
                    final_path = base + ".mp4"
                
                if not os.path.exists(final_path):
                    yield log("Download failed, file not found."), None
                    return
                
                yield log("Download complete. Starting post-processing..."), None
                
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else "ffmpeg"

                if opt_extract_frame or opt_extract_prompt:
                    yield log("Extracting frame..."), None
                    frame_path = base + "_first_frame.jpg"
                    subprocess.run([ffmpeg_exe, "-y", "-i", final_path, "-vframes", "1", "-q:v", "2", frame_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(frame_path):
                        if opt_extract_frame:
                            final_files_to_return.append(frame_path)
                        if opt_extract_prompt:
                            yield log("Extracting AI Prompt (BLIP)..."), None
                            try:
                                from ai_prompter import extract_prompt_from_image
                                prompt_text = extract_prompt_from_image(frame_path)
                                prompt_txt_path = base + "_prompt.txt"
                                with open(prompt_txt_path, "w", encoding="utf-8") as f:
                                    f.write(prompt_text)
                                final_files_to_return.append(prompt_txt_path)
                            except Exception as e:
                                yield log(f"Prompt Extraction Error: {str(e)}"), None
                
                if opt_identify_song:
                    yield log("Identifying song & metadata..."), None
                    song_txt_path = base + "_song.txt"
                    temp_audio = base + "_temp_audio.mp3"
                    subprocess.run([ffmpeg_exe, "-y", "-i", final_path, "-t", "15", "-vn", "-acodec", "libmp3lame", temp_audio], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    shazam_track, shazam_artist = None, None
                    if os.path.exists(temp_audio):
                        shazam_res = shazam_file(temp_audio)
                        if shazam_res and 'track' in shazam_res:
                            shazam_track = shazam_res['track'].get('title')
                            shazam_artist = shazam_res['track'].get('subtitle')
                        try: os.remove(temp_audio)
                        except: pass
                    
                    yt_track = info.get('track') or info.get('alt_title')
                    yt_artist = info.get('artist') or info.get('creator')
                    yt_desc = info.get('description', '')
                    
                    with open(song_txt_path, "w", encoding="utf-8") as f:
                        f.write("--- VIDEO AUDIO INFO ---\n\n")
                        if shazam_track:
                            f.write(f" Shazam Match:\nSong: {shazam_track}\nArtist: {shazam_artist}\n\n")
                        else:
                            f.write(f" Shazam Match: No match found.\n\n")
                        f.write(f" Original Upload Metadata (yt-dlp):\nTrack: {yt_track or 'Unknown'}\nArtist/Creator: {yt_artist or 'Unknown'}\n")
                    final_files_to_return.append(song_txt_path)
                    
                    if yt_desc:
                        caption_txt_path = base + "_caption.txt"
                        with open(caption_txt_path, "w", encoding="utf-8") as f: f.write(yt_desc)
                        final_files_to_return.append(caption_txt_path)
                
                if opt_transcribe:
                    yield log("Transcribing speech..."), None
                    transcript_path = base + "_transcript.txt"
                    full_audio = base + "_full_audio.mp3"
                    subprocess.run([ffmpeg_exe, "-y", "-i", final_path, "-vn", "-acodec", "libmp3lame", full_audio], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    if os.path.exists(full_audio):
                        try:
                            model = get_whisper()
                            if model:
                                result = model.transcribe(full_audio, verbose=False)
                                with open(transcript_path, "w", encoding="utf-8") as f:
                                    f.write(result.get("text", "").strip())
                                final_files_to_return.append(transcript_path)
                        except Exception as e:
                            print("Whisper error:", e)
                        try: os.remove(full_audio)
                        except: pass
                
                is_video = final_path.lower().endswith(('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'))
                if opt_force_h264 and is_video:
                    yield log("Forcing Standard Encoding (H.264)..."), None
                    temp_h264 = base + "_h264_temp.mp4"
                    res = subprocess.run([ffmpeg_exe, "-y", "-i", final_path, "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", temp_h264], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    if res.returncode == 0 and os.path.exists(temp_h264) and os.path.getsize(temp_h264) > 1024:
                        if not final_path.endswith('.mp4'):
                            try: os.remove(final_path)
                            except: pass
                            final_path = base + ".mp4"
                        os.replace(temp_h264, final_path)
                    else:
                        err_msg = res.stderr.decode('utf-8', errors='ignore')[-200:] if res.stderr else "Unknown FFmpeg error"
                        yield log(f"H.264 Encode Failed! Kept original. ({err_msg})"), None
                        try: os.remove(temp_h264)
                        except: pass
                        
                if opt_ai_bypass:
                    yield log("Applying AI Bypass (Scramble & Clean)..."), None
                    try:
                        from cleaner import clean_video, clean_photo
                        ext = final_path.split('.')[-1].lower()
                        is_vid = ext in ['mp4', 'mov', 'm4v', 'webm', 'avi', 'mkv']
                        
                        if is_vid: success, msg = clean_video(final_path, ffmpeg_exe)
                        else: success, msg = clean_photo(final_path)
                            
                        if not success: yield log(f"AI Bypass Failed: {msg}"), None
                    except Exception as e:
                        yield log(f"AI Bypass Error: {e}"), None
                final_files_to_return.insert(0, final_path)

                title = info.get('title', 'Unknown Title')
                uploader = info.get('uploader', 'Unknown')
                platform = info.get('extractor_key', 'Other')
                add_history_entry(url, title, uploader, final_path, platform)

                yield log("All processing complete! Files are ready to download."), final_files_to_return

    except Exception as e:
        error_msg = str(e)
        error_msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', error_msg)
        yield log(f"Error: {error_msg}"), None


@spaces.GPU(duration=120)
def process_conversion(files, resize, format_opt, autocrop, burn_subtitles, trim_start, trim_end, compress_opt):
    if not files:
        yield "Error: No files uploaded.", None
        return
        
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(WEB_DOWNLOADS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else "ffmpeg"
    
    log_msgs = []
    def log(msg):
        log_msgs.append(msg)
        return "\n".join(log_msgs[-10:])
        
    final_files = []
    total = len(files)
    
    for idx, f in enumerate(files, 1):
        yield log(f"[{idx}/{total}] Processing {os.path.basename(f)}..."), final_files
        
        input_path = f
        input_ext = os.path.splitext(f)[1].lower()
        base_name = os.path.splitext(os.path.basename(f))[0]
        output_name = f"{base_name}_converted.{format_opt}"
        output_path = os.path.join(task_dir, output_name)
        
        cmd = [ffmpeg_exe, "-y"]
        if trim_start and trim_start.strip(): cmd.extend(["-ss", trim_start.strip()])
        cmd.extend(["-i", input_path])
        if trim_end and trim_end.strip(): cmd.extend(["-to", trim_end.strip()])
            
        try:
            vf_filters = []
            crf_val = "23"
            
            if autocrop and format_opt not in ["mp3", "wav"] and input_ext not in [".mp3", ".wav", ".jpg", ".png", ".webp"]:
                yield log(f"[{idx}/{total}] Analyzing face position..."), final_files
                center_x = get_face_center_x(input_path)
                if center_x is not None: vf_filters.append(f"crop=ih*9/16:ih:{center_x}-ih*9/32:0")
                else: vf_filters.append("crop=ih*9/16:ih")
            elif resize and resize != "none" and format_opt not in ["mp3", "wav"]:
                if resize == "crop_9_16": vf_filters.append("crop=ih*9/16:ih")
                elif resize == "pad_9_16": vf_filters.append("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
                elif resize == "crop_16_9": vf_filters.append("crop=iw:iw*9/16")
                elif resize == "pad_16_9": vf_filters.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
                elif resize == "crop_1_1": vf_filters.append("crop=min(iw\\,ih):min(iw\\,ih)")
                elif resize == "crop_4_5": vf_filters.append("crop=ih*4/5:ih")
                elif resize == "pad_blur_9_16": vf_filters.append("split[original][copy];[copy]scale=-1:1920,crop=1080:1920,boxblur=20:5[bg];[original]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")

            if compress_opt and compress_opt != "none" and format_opt not in ["mp3", "wav"]:
                if compress_opt == "scale_1080p": vf_filters.append("scale='min(1080,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease")
                elif compress_opt == "scale_720p": vf_filters.append("scale='min(720,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease"); crf_val = "26"
                elif compress_opt == "scale_480p": vf_filters.append("scale='min(480,iw)':'min(854,ih)':force_original_aspect_ratio=decrease"); crf_val = "28"
                elif compress_opt == "scale_50": vf_filters.append("scale=iw*0.5:ih*0.5"); crf_val = "26"
                elif compress_opt == "scale_25": vf_filters.append("scale=iw*0.25:ih*0.25"); crf_val = "28"
                elif compress_opt == "compress_high": crf_val = "28"
                elif compress_opt == "compress_web": crf_val = "32"
            
            if format_opt in ["mp3", "wav"]:
                if format_opt == "mp3": cmd.extend(["-vn", "-acodec", "libmp3lame", "-q:a", "2"])
                else: cmd.extend(["-vn", "-acodec", "pcm_s16le"])
            else:
                if burn_subtitles:
                    yield log(f"[{idx}/{total}] Burning subtitles..."), final_files
                    temp_audio = os.path.join(task_dir, f"{uuid.uuid4().hex}.mp3")
                    temp_srt = os.path.join(task_dir, f"{uuid.uuid4().hex}.srt")
                    subprocess.run([ffmpeg_exe, "-y", "-i", input_path, "-vn", "-acodec", "libmp3lame", temp_audio], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(temp_audio):
                        try:
                            model = get_whisper()
                            if model:
                                result = model.transcribe(temp_audio, verbose=False)
                                def format_time(seconds):
                                    m, s = divmod(seconds, 60)
                                    h, m = divmod(m, 60)
                                    ms = int((s - int(s)) * 1000)
                                    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"
                                with open(temp_srt, 'w', encoding='utf-8') as fsrt:
                                    for i, segment in enumerate(result.get('segments', [])):
                                        fsrt.write(f"{i + 1}\n{format_time(segment['start'])} --> {format_time(segment['end'])}\n{segment['text'].strip()}\n\n")
                                srt_escaped = temp_srt.replace('\\', '\\\\').replace(':', '\\:')
                                vf_filters.append(f"subtitles='{srt_escaped}':force_style='FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2'")
                        except: pass

                if vf_filters: cmd.extend(["-vf", ",".join(vf_filters)])
                
                if format_opt in ["mp4", "mkv", "mov", "avi"]: cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", crf_val, "-c:a", "aac", "-pix_fmt", "yuv420p"])
                elif format_opt == "webm": cmd.extend(["-c:v", "libvpx", "-c:a", "libvorbis", "-crf", crf_val])
                elif format_opt == "gif": cmd.extend(["-r", "15"]) 
                elif format_opt in ["jpg", "png", "webp"]:
                    if input_ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi']: cmd.extend(["-vframes", "1"])
                    
            cmd.append(output_path)
            yield log(f"[{idx}/{total}] Encoding..."), final_files
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            final_files.append(output_path)
            
        except Exception as e:
            yield log(f"[{idx}/{total}] Error: {str(e)}"), final_files
            
    yield log("Conversion complete!"), final_files


@spaces.GPU(duration=120)
def process_cleaner(files, inject_exif):
    if not files:
        yield "Error: No files uploaded.", None
        return
        
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(WEB_DOWNLOADS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    
    log_msgs = []
    def log(msg):
        log_msgs.append(msg)
        return "\n".join(log_msgs[-10:])
        
    final_files = []
    
    try:
        from cleaner import run_batch_cleaner
        # Move files to task_dir manually to emulate 'is_upload=True' behavior in cleaner.py
        target_files = []
        for f in files:
            target = os.path.join(task_dir, os.path.basename(f))
            shutil.copy2(f, target)
            target_files.append(target)
            
        cleaner_generator = run_batch_cleaner(target_files, task_dir, is_upload=True, inject_exif=inject_exif)
        
        for msg_sse in cleaner_generator:
            try:
                msg_json = json.loads(msg_sse.replace("data: ", "").strip())
                if "status" in msg_json:
                    yield log(msg_json["status"]), final_files
            except: pass
            
        for root, dirs, f_list in os.walk(task_dir):
            for f in f_list:
                if f != "scramble_registry.txt" and f != "video_scramble_registry.txt":
                    final_files.append(os.path.join(root, f))
                    
        yield log("Cleaning complete!"), final_files
    except Exception as e:
        yield log(f"Error: {e}"), final_files


def load_gallery():
    media = []
    if os.path.exists(WEB_DOWNLOADS_DIR):
        for root, _, files in os.walk(WEB_DOWNLOADS_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                if file == "history.json" or file.endswith(".srt") or file.endswith("registry.txt"): continue
                ext = os.path.splitext(file)[1].lower()
                if ext in ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp3', '.wav', '.txt']:
                    media.append(file_path)
    # Sort by modification time (newest first)
    media.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return media

# --- UI Definition ---

custom_css = """
body, .gradio-container {
    background-color: #050508 !important;
    color: #FFFFFF !important;
    font-family: 'Inter', system-ui, sans-serif !important;
}
.dark-container {
    background: rgba(20, 20, 35, 0.6) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 16px !important;
    padding: 24px !important;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5) !important;
    margin-bottom: 16px !important;
}
.magenta-btn {
    background: linear-gradient(135deg, #FF00FF, #8A2BE2) !important;
    border: none !important;
    color: white !important;
    font-weight: 800 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    border-radius: 12px !important;
    box-shadow: 0 0 20px rgba(255, 0, 255, 0.3) !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    padding: 12px 24px !important;
}
.magenta-btn:hover {
    transform: translateY(-2px) scale(1.02) !important;
    box-shadow: 0 0 30px rgba(255, 0, 255, 0.6) !important;
}
.pink-header {
    color: #FF00FF !important;
    font-weight: 800 !important;
    letter-spacing: 1px !important;
    margin-bottom: 15px !important;
    font-size: 1.2rem !important;
}
.status-header {
    background: rgba(20, 20, 35, 0.8) !important;
    backdrop-filter: blur(10px) !important;
    border-bottom: 2px solid #FF00FF !important;
    padding: 20px !important;
    margin-bottom: 25px !important;
    border-radius: 12px 12px 0 0 !important;
    box-shadow: 0 4px 20px rgba(255, 0, 255, 0.15) !important;
}
.status-header h1 {
    margin: 0 !important;
    font-size: clamp(1.2rem, 4vw, 1.8rem) !important;
    font-weight: 900 !important;
    display: flex !important;
    flex-wrap: wrap !important;
    justify-content: space-between !important;
    align-items: center !important;
    gap: 10px !important;
}
.status-header .engine-online {
    color: #00FF00 !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    background: rgba(0, 255, 0, 0.1) !important;
    padding: 4px 12px !important;
    border-radius: 20px !important;
    border: 1px solid rgba(0, 255, 0, 0.3) !important;
}
input[type="text"], textarea {
    background: rgba(0, 0, 0, 0.4) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    color: white !important;
    border-radius: 8px !important;
    padding: 12px !important;
    transition: all 0.3s ease !important;
}
input[type="text"]:focus, textarea:focus {
    border-color: #FF00FF !important;
    box-shadow: 0 0 10px rgba(255, 0, 255, 0.2) !important;
}
.tab-nav {
    border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
    margin-bottom: 20px !important;
}
.tab-nav button {
    font-weight: 600 !important;
    padding: 12px 20px !important;
}
/* Mobile specific optimizations */
@media (max-width: 768px) {
    .dark-container {
        padding: 15px !important;
        margin-bottom: 12px !important;
    }
    .status-header {
        padding: 15px !important;
    }
    .gradio-container {
        padding: 10px !important;
    }
}
"""

with gr.Blocks(css=custom_css, theme=gr.themes.Default(primary_hue="fuchsia")) as demo:
    with gr.Column(visible=True, elem_classes="dark-container") as login_screen:
        gr.Markdown("<h1 class='pink-header' style='text-align:center;'>🔒 RESTRICTED ACCESS</h1>")
        pw_input = gr.Textbox(type="password", label="Enter Password", placeholder="••••••••")
        login_btn = gr.Button("UNLOCK SYSTEM", elem_classes="magenta-btn")
        login_err = gr.Markdown(visible=False)

    with gr.Column(visible=False) as main_app:
        gr.HTML('''
    <div class="status-header">
        <h1>AI INFLUENCER MEDIA GRABBER V1.6 <span class="engine-online">● Engine Online</span></h1>
    </div>
    ''')
    
        with gr.Accordion("❓ Master Features & Tab Guide", open=False):
            gr.Markdown("""
            ### 🎛️ STUDIO TAB
            - **Batch Link Downloader**: Paste TikTok, IG Reels, YouTube Shorts, X/Twitter, or Pinterest links (one per line).
            - **Force H.264 Encoding**: Fixes video import glitches in CapCut, Kling AI, and Premiere.
            - **Transcribe Audio (Whisper)**: Converts video speech into text transcriptions.
            - **Identify Song (Shazam)**: Detects background music titles and artists.
            - **Extract First Frame**: Generates video cover thumbnails.
            - **Extract AI Prompt**: Pulls AI prompts into `.txt` files.
            - **Auto-Storage Cleaner**: Automatically deletes files older than 1 hour to keep cloud storage 100% free.

            ### 🛠️ MEDIA TOOLS TAB
            - Format converter, audio extractor (MP3/WAV), and resolution/bitrate adjustments for local and processed media files.

            ### 🛡️ AI CLEANER TAB
            - Standalone metadata scrubbing and C2PA AI watermark removal to bypass social media AI detection algorithms.

            ### 🖼️ GALLERY TAB
            - Interactive grid to view, play, and download all active processed files sitting in `./web_downloads`.

            ### 📜 HISTORY TAB
            - Review past download logs, execution timestamps, and task status details.
            """)
            
        with gr.Tabs():
            # TAB 1: STUDIO
            with gr.TabItem("STUDIO"):
                with gr.Row():
                    with gr.Column(scale=2, min_width=320):
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>01. MEDIA URL</h3>")
                            url_input = gr.Textbox(placeholder="Paste YouTube, Instagram, TikTok, Twitter URL here...", label="Media URL", lines=2)
                            custom_name = gr.Textbox(placeholder="Optional: Custom Filename", label="Custom Filename")
                            
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>02. PROCESSING OPTIONS</h3>")
                            options = gr.CheckboxGroup(
                                choices=[
                                    "Force H.264 Encoding",
                                    "Extract First Frame",
                                    "Extract AI Prompt (BLIP)",
                                    "Identify Song Metadata",
                                    "Transcribe Audio (Whisper)",
                                    "AI Bypass (Scramble & Clean)"
                                ],
                                label="Select processing steps",
                                value=["Force H.264 Encoding", "Extract First Frame"]
                            )
                            
                        process_btn = gr.Button("START DOWNLOADING MEDIA", elem_classes="magenta-btn", size="lg")
                        
                    with gr.Column(scale=1, min_width=320):
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>03. TASK QUEUE & LOGS</h3>")
                            status_log = gr.Textbox(label="Status Log", lines=8, interactive=False)
                            output_files = gr.File(label="Output Files", interactive=False)
                            
                process_btn.click(fn=process_download, inputs=[url_input, options, custom_name], outputs=[status_log, output_files])

            # TAB 2: MEDIA TOOLS
            with gr.TabItem("MEDIA TOOLS"):
                with gr.Row():
                    with gr.Column(scale=2, min_width=320):
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>FORMAT CONVERTER</h3>")
                            conv_files = gr.File(label="Upload Media Files", file_count="multiple")
                            
                            with gr.Row():
                                conv_format = gr.Dropdown(
                                    choices=["mp4", "mp3", "gif", "jpg", "png", "webm", "wav"],
                                    label="Output Format", value="mp4"
                                )
                                conv_resize = gr.Dropdown(
                                    choices=["none", "crop_9_16", "pad_9_16", "pad_blur_9_16", "crop_1_1", "crop_16_9"],
                                    label="Resize / Framing", value="none"
                                )
                                conv_compress = gr.Dropdown(
                                    choices=["none", "scale_1080p", "scale_720p", "compress_high", "compress_web"],
                                    label="Compression", value="none"
                                )
                                
                            with gr.Row():
                                conv_autocrop = gr.Checkbox(label="Smart Auto-Crop (Face Detect)")
                                conv_subtitles = gr.Checkbox(label="Burn Auto-Subtitles (Whisper)")
                                
                            with gr.Row():
                                conv_trim_start = gr.Textbox(label="Trim Start (e.g. 00:00:10)", placeholder="HH:MM:SS")
                                conv_trim_end = gr.Textbox(label="Trim End (e.g. 00:00:20)", placeholder="HH:MM:SS")
                                
                        conv_btn = gr.Button("START CONVERSION", elem_classes="magenta-btn", size="lg")
                        
                    with gr.Column(scale=1, min_width=320):
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>LOGS</h3>")
                            conv_log = gr.Textbox(label="Status Log", lines=8, interactive=False)
                            conv_output = gr.File(label="Converted Files", interactive=False)
                            
                conv_btn.click(
                    fn=process_conversion,
                    inputs=[conv_files, conv_resize, conv_format, conv_autocrop, conv_subtitles, conv_trim_start, conv_trim_end, conv_compress],
                    outputs=[conv_log, conv_output]
                )

            # TAB 3: AI CLEANER
            with gr.TabItem("AI CLEANER"):
                with gr.Row():
                    with gr.Column(scale=2, min_width=320):
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>BATCH AI CLEANER</h3>")
                            gr.Markdown("Strip metadata, scramble C2PA patterns, and apply microscopic visual noise to completely bypass AI detector classifiers.")
                            cleaner_files = gr.File(label="Upload Media Files", file_count="multiple")
                            cleaner_exif = gr.Checkbox(label="Inject Fake iPhone 15 Pro EXIF Metadata", value=True)
                            
                        cleaner_btn = gr.Button("RUN BATCH CLEANER", elem_classes="magenta-btn", size="lg")
                        
                    with gr.Column(scale=1, min_width=320):
                        with gr.Group(elem_classes="dark-container"):
                            gr.Markdown("<h3 class='pink-header'>LOGS</h3>")
                            cleaner_log = gr.Textbox(label="Status Log", lines=8, interactive=False)
                            cleaner_output = gr.File(label="Cleaned Files", interactive=False)
                            
                cleaner_btn.click(fn=process_cleaner, inputs=[cleaner_files, cleaner_exif], outputs=[cleaner_log, cleaner_output])

            # TAB 4: GALLERY
            with gr.TabItem("GALLERY"):
                with gr.Group(elem_classes="dark-container"):
                    gr.Markdown("<h3 class='pink-header'>SERVER CACHE GALLERY</h3>")
                    gr.Markdown("Note: Files are automatically deleted 1 hour after generation to save disk space.")
                    refresh_gallery_btn = gr.Button("Refresh Gallery")
                    gallery_output = gr.Gallery(label="Cached Media", columns=4)
                    gallery_files_output = gr.File(label="Download Direct Files", interactive=False)
                    
                def refresh_gal():
                    g = load_gallery()
                    return g, g
                    
                refresh_gallery_btn.click(fn=refresh_gal, inputs=[], outputs=[gallery_output, gallery_files_output])
                # Auto-load on mount
                demo.load(fn=refresh_gal, inputs=[], outputs=[gallery_output, gallery_files_output])

            # TAB 5: HISTORY
            with gr.TabItem("HISTORY"):
                with gr.Group(elem_classes="dark-container"):
                    gr.Markdown("<h3 class='pink-header'>DOWNLOAD HISTORY</h3>")
                    with gr.Row():
                        refresh_hist_btn = gr.Button("Refresh History")
                        clear_hist_btn = gr.Button("Clear History", variant="stop")
                        
                    hist_output = gr.Dataframe(headers=["Time", "Platform", "Title", "Uploader", "URL", "File"])
                    
                refresh_hist_btn.click(fn=load_history_df, inputs=[], outputs=[hist_output])
                clear_hist_btn.click(fn=clear_history_fn, inputs=[], outputs=[hist_output])
                demo.load(fn=load_history_df, inputs=[], outputs=[hist_output])

    def check_pw(pw):
        if pw == os.environ.get("WEB_PASSWORD", "EmpressMin26"):
            return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)
        return gr.update(visible=True), gr.update(visible=False), gr.update(value="<h3 style='color:red;text-align:center;'>❌ ACCESS DENIED</h3>", visible=True)

    login_btn.click(fn=check_pw, inputs=[pw_input], outputs=[login_screen, main_app, login_err])
    pw_input.submit(fn=check_pw, inputs=[pw_input], outputs=[login_screen, main_app, login_err])

if __name__ == "__main__":
    print(f"Starting server with In-App Auth enabled.")
    
    demo.launch(
        server_name="0.0.0.0", 
        server_port=7860,
        css=custom_css,
        theme=gr.themes.Default(primary_hue="fuchsia")
    )
