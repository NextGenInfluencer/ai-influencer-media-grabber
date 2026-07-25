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
import spaces
from pathlib import Path

# Fix: some libraries might not be available if not installed properly, we handle them gracefully if needed
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

# Ensure ffmpeg is in PATH for whisper
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

# Local web downloads directory
WEB_DOWNLOADS_DIR = os.path.join(os.getcwd(), "web_downloads")
os.makedirs(WEB_DOWNLOADS_DIR, exist_ok=True)

# Auto-cleanup thread to keep disk free (Deletes files older than 1 hour)
def cleanup_daemon():
    while True:
        try:
            current_time = time.time()
            for root, dirs, files in os.walk(WEB_DOWNLOADS_DIR):
                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        # If file is older than 3600 seconds (1 hour)
                        if current_time - os.path.getmtime(file_path) > 3600:
                            os.remove(file_path)
                            print(f"[Cleanup] Deleted {file_path}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"Cleanup error: {e}")
        time.sleep(600) # Check every 10 minutes

threading.Thread(target=cleanup_daemon, daemon=True).start()

@spaces.GPU
def process_download(url, options):
    if not yt_dlp:
        yield "Error: yt-dlp is not installed.", None
        return

    url = url.strip()
    if not url:
        yield "Error: No URL provided.", None
        return

    # Parse options
    opt_force_h264 = "Force H.264 Encoding" in options
    opt_extract_frame = "Extract First Frame" in options
    opt_extract_prompt = "Extract AI Prompt (BLIP)" in options
    opt_identify_song = "Identify Song Metadata" in options
    opt_transcribe = "Transcribe Audio (Whisper)" in options
    opt_ai_bypass = "AI Bypass (Scramble & Clean)" in options

    yield f"Starting process for: {url}", None
    
    # Create an isolated task directory
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(WEB_DOWNLOADS_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best' if opt_force_h264 else 'bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': os.path.join(task_dir, '%(title)s_%(id)s.%(ext)s'),
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
        return "\n".join(log_msgs[-10:]) # Show last 10 lines

    def hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').strip()
            percent = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', percent)
            # We don't yield here directly as gradio generator from hook is tricky,
            # but we could store it in a state. For simplicity, we just let it download.
        
    ydl_opts['progress_hooks'] = [hook]

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
                
                final_files_to_return.append(final_path)
                yield log("Download complete. Starting post-processing..."), None
                
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe() if imageio_ffmpeg else "ffmpeg"

                # 1. Extract Frame
                if opt_extract_frame or opt_extract_prompt:
                    yield log("Extracting frame..."), None
                    frame_path = base + "_first_frame.jpg"
                    ffmpeg_cmd = [
                        ffmpeg_exe, "-y", "-i", final_path,
                        "-vframes", "1", "-q:v", "2", frame_path
                    ]
                    subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(frame_path):
                        if opt_extract_frame:
                            final_files_to_return.append(frame_path)
                            
                        # 2. Extract AI Prompt
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
                
                # 3. Audio Recognition & Metadata
                if opt_identify_song:
                    yield log("Identifying song & metadata..."), None
                    song_txt_path = base + "_song.txt"
                    temp_audio = base + "_temp_audio.mp3"
                    
                    ffmpeg_audio_cmd = [
                        ffmpeg_exe, "-y", "-i", final_path,
                        "-t", "15", "-vn", "-acodec", "libmp3lame", temp_audio
                    ]
                    subprocess.run(ffmpeg_audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
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
                            f.write(f" Shazam Match:\n")
                            f.write(f"Song: {shazam_track}\n")
                            f.write(f"Artist: {shazam_artist}\n\n")
                        else:
                            f.write(f" Shazam Match: No match found.\n\n")
                            
                        f.write(f" Original Upload Metadata (yt-dlp):\n")
                        f.write(f"Track: {yt_track or 'Unknown'}\n")
                        f.write(f"Artist/Creator: {yt_artist or 'Unknown'}\n")
                    final_files_to_return.append(song_txt_path)
                    
                    if yt_desc:
                        caption_txt_path = base + "_caption.txt"
                        with open(caption_txt_path, "w", encoding="utf-8") as f:
                            f.write(yt_desc)
                        final_files_to_return.append(caption_txt_path)
                
                # 4. Transcribe Video (Whisper)
                if opt_transcribe:
                    yield log("Transcribing speech..."), None
                    transcript_path = base + "_transcript.txt"
                    full_audio = base + "_full_audio.mp3"
                    
                    ffmpeg_full_audio = [
                        ffmpeg_exe, "-y", "-i", final_path,
                        "-vn", "-acodec", "libmp3lame", full_audio
                    ]
                    subprocess.run(ffmpeg_full_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
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
                
                # 5. Force H.264
                if opt_force_h264 and final_path.endswith('.mp4'):
                    yield log("Forcing Standard Encoding (H.264)..."), None
                    temp_h264 = base + "_h264_temp.mp4"
                    ffmpeg_h264_cmd = [
                        ffmpeg_exe, "-y", "-i", final_path,
                        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                        "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", temp_h264
                    ]
                    subprocess.run(ffmpeg_h264_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(temp_h264):
                        os.replace(temp_h264, final_path)
                        
                # 6. AI Bypass
                if opt_ai_bypass:
                    yield log("Applying AI Bypass (Scramble & Clean)..."), None
                    try:
                        from cleaner import clean_video, clean_photo
                        ext = final_path.split('.')[-1].lower()
                        is_vid = ext in ['mp4', 'mov', 'm4v', 'webm', 'avi', 'mkv']
                        
                        if is_vid:
                            success, msg = clean_video(final_path, ffmpeg_exe)
                        else:
                            success, msg = clean_photo(final_path)
                            
                        if not success:
                            yield log(f"AI Bypass Failed: {msg}"), None
                    except Exception as e:
                        yield log(f"AI Bypass Error: {e}"), None

                yield log("All processing complete! Files are ready to download."), final_files_to_return

    except Exception as e:
        error_msg = str(e)
        error_msg = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', error_msg)
        yield log(f"Error: {error_msg}"), None

# --- UI Definition ---

custom_css = """
body, .gradio-container {
    background-color: #0A0A0F !important;
    color: #FFFFFF !important;
    font-family: 'Inter', sans-serif !important;
}
.dark-container {
    background-color: #12121B !important;
    border: 1px solid #2A2A35 !important;
    border-radius: 8px !important;
    padding: 20px !important;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5) !important;
}
.magenta-btn {
    background: linear-gradient(90deg, #FF00FF, #8A2BE2) !important;
    border: none !important;
    color: white !important;
    font-weight: 800 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    box-shadow: 0 0 15px rgba(255, 0, 255, 0.4) !important;
    transition: all 0.3s ease !important;
}
.magenta-btn:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 0 25px rgba(255, 0, 255, 0.7) !important;
}
.pink-header {
    color: #FF00FF !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    margin-bottom: 10px !important;
}
.status-header {
    background: #1A1A24 !important;
    border-bottom: 2px solid #FF00FF !important;
    padding: 15px 20px !important;
    margin-bottom: 30px !important;
    border-radius: 8px 8px 0 0 !important;
}
.status-header h1 {
    margin: 0 !important;
    font-size: 1.5rem !important;
    font-weight: 900 !important;
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
}
.status-header .engine-online {
    color: #00FF00 !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
}
input[type="text"], textarea {
    background-color: #1A1A24 !important;
    border: 1px solid #333344 !important;
    color: white !important;
}
"""

with gr.Blocks() as demo:
    gr.HTML('''
    <div class="status-header">
        <h1>AI INFLUENCER MEDIA GRABBER V1.6 <span class="engine-online">● Engine Online</span></h1>
    </div>
    ''')
    
    with gr.Row():
        with gr.Column(scale=2):
            with gr.Group(elem_classes="dark-container"):
                gr.Markdown("<h3 class='pink-header'>01. VIDEO OR CAROUSEL URLS</h3>")
                url_input = gr.Textbox(
                    placeholder="Paste YouTube, Instagram, TikTok, Twitter URL here...",
                    label="Media URL",
                    lines=2
                )
                
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
            
        with gr.Column(scale=1):
            with gr.Group(elem_classes="dark-container"):
                gr.Markdown("<h3 class='pink-header'>03. OUTPUT & LOGS</h3>")
                status_log = gr.Textbox(label="Status Log", lines=8, interactive=False)
                output_files = gr.File(label="Downloaded / Processed Files", interactive=False)
                
    process_btn.click(
        fn=process_download,
        inputs=[url_input, options],
        outputs=[status_log, output_files]
    )

if __name__ == "__main__":
    # Get credentials from environment variables (Hugging Face Secrets) or use defaults
    auth_user = os.environ.get("WEB_USERNAME", "admin")
    auth_pass = os.environ.get("WEB_PASSWORD", "influencer123")
    
    print(f"Starting server with Basic Auth enabled for user: {auth_user}")
    
    demo.launch(
        server_name="0.0.0.0", 
        server_port=7860,
        auth=(auth_user, auth_pass),
        css=custom_css,
        theme=gr.themes.Default(primary_hue="fuchsia")
    )

