# AI Influencer Media Grabber & Creator Studio

![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows)
![100% Local](https://img.shields.io/badge/Processing-100%25%20Local-0a84ff?style=for-the-badge)
![GPU Accelerated](https://img.shields.io/badge/GPU-NVENC%20%2F%20QSV%20%2F%20AMF%20%2F%20CPU-30d158?style=for-the-badge)
![AI Engine](https://img.shields.io/badge/Offline%20AI-Whisper%20%C2%B7%20BLIP%20%C2%B7%20Llama%20%C2%B7%20Qwen3-a855f7?style=for-the-badge)

**A complete Windows desktop suite for downloading high-quality social media videos, MP3 audio, and photo carousels; converting, trimming, and face-tracking clips offline; cleaning AI metadata; preparing Nano Banana → Kling references; and editing multi-clip music & lyric videos.**

Everything runs locally on your PC inside a fast, Apple macOS-inspired desktop interface — with no monthly cloud subscriptions, no upload size limits, and full hardware GPU acceleration.

[📥 Download Latest Windows Installer (`Setup.exe`)](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases/latest) · [📋 Release Notes](RELEASE_NOTES.md) · [🕓 Changelog](CHANGELOG.md) · [🎤 Lyrics & Translation Guide](docs/creator-lyrics-guide.md)

---

## 📸 Visual Tour

<div align="center">
  <img src="assets/ui_downloader.png" width="49%" alt="Downloader Tab: Multi-link queueing, MP3/4K quality, and AI pipeline tiles" />
  <img src="assets/ui_converter.png" width="49%" alt="Media Tools Tab: Trimming, face-tracking 9:16 crop, compression, and FX" />
  <br>
  <img src="assets/ui_gallery_preview.png" width="49%" alt="Output Gallery: Search, filter, lightbox preview, and source-post tracking" />
  <img src="assets/ui_cleaner.png" width="49%" alt="AI Cleaner Tab: Strip SynthID/C2PA/EXIF tags and inject camera metadata" />
</div>

---

## 🧭 Complete Feature Guide (Tab by Tab)

The application is organized into six main workspace tabs across the top navigation bar (**Downloader**, **Media Tools**, **AI Cleaner**, **Captions Studio**, **Gallery**, **History**), a **More Tools (`⋯`)** menu (**Kling Prep** & **Carousel Studio**), and a permanent right-hand **Activity Hub & Live Console**.

---

### 1. ⬇️ Downloader Tab (Social Video, Carousel & YouTube-to-MP3 Grabber)

Download reference videos, music/audio tracks, photos, and multi-slide carousels from major platforms in one click.

- **Supported Platforms**:
  - **YouTube & YouTube Shorts**: Full videos, Shorts, playlists, or **direct MP3 audio extraction**.
  - **TikTok**: Grab reference videos using the best available unwatermarked source stream.
  - **Instagram**: Download Reels, single photos, and multi-slide photo/video carousels (with automatic `gallery-dl` fallback).
  - **X (Twitter), Pinterest, Vimeo & More**: Powered by an isolated, up-to-date `yt-dlp` and `gallery-dl` engine.
- **Batch Multi-Link Queueing**:
  - Paste one or dozens of URLs at once (one per line) or click **`📋 Paste Link`**.
  - Platform badges (**TikTok**, **Instagram**, **YouTube**, **X**, **Pinterest**, **Vimeo**) light up automatically as links are detected.
- **Resolution & Audio-Only (`MP3`) Selector**:
  - Choose **`Max Quality (4K / 2K / Best)`**, **`4K Ultra HD (2160p)`**, **`2K Quad HD (1440p)`**, **`1080p Full HD`**, **`720p HD`**, **`480p SD`**, or **`Audio Only (MP3)`** to download YouTube songs, backing tracks, and podcasts directly as MP3 files.
- **Browser Cookie Authentication**:
  - Use **`Anonymous (Public Media)`** by default, or select your local **Chrome**, **Firefox**, **Edge**, or **Safari** profile (or a custom `cookies.txt` file) to access age-restricted, private, or login-required posts.
- **Custom Save Destination**:
  - Saves automatically to `Documents/Media Grabber` (neatly sorted into `YouTube/`, `TikTok/`, `Instagram/`, etc.), or pick any custom folder on any drive and click **`Reveal`** to open it in Windows Explorer.
- **9 Automated Processing & AI Pipeline Tiles** *(optional toggles that run automatically on every download)*:
  1. **Force H.264**: Re-encodes downloaded streams into universal H.264/AAC `.mp4` so files import cleanly into Premiere Pro, DaVinci Resolve, CapCut, and Kling.
  2. **Extract First Frame**: Automatically saves a high-resolution cover/reference image (`first_frame`) alongside the video.
  3. **Clean Metadata**: Strips source container tracking metadata and saves a sanitized copy while keeping a backup.
  4. **Identify Song (Shazam)**: Fingerprints the audio track to identify the song title and artist automatically, displaying the result in the queue and saving it to your History.
  5. **Transcribe Audio**: Runs offline **Whisper AI** speech-to-text on the downloaded media.
  6. **Burn Subtitles**: Hardcodes styled captions directly onto the downloaded video.
  7. **Export `.SRT` File**: Saves a standalone `.srt` subtitle timing file next to the video.
  8. **Scene Prompt**: Uses local **BLIP Vision** + **Local LLM** (`Llama 3.2 1B` or `Llama 3 8B`) to write a detailed `.txt` visual prompt describing the subject, lighting, camera angle, and outfit.
  9. **Smart SEO & Hooks**: Uses the local LLM to generate a `.txt` summary with viral hooks, key takeaways, and social hashtags.

---

### 2. 🎛️ Media Tools Tab (Offline Converter, Trimmer, Face-Tracking Crop & FX)

Edit, convert, compress, and re-frame any local video, audio, or image file completely offline — no download required.

- **Interactive Video Trimmer**:
  - Drag and drop any file, preview it in the built-in player, set **`Start Time`** and **`End Time`** (`HH:MM:SS`), or click the crosshair buttons (`🎯`) to lock the current playhead position and see the exact cut length.
- **Aspect Ratio Cropping, Padding & Blurred Canvas**:
  - Convert between **Vertical (`9:16`)** for TikTok/Reels/Shorts (`Crop to 9:16 Fill`, `Pad to 9:16 Letterbox`, or **`Pad 16:9 to 9:16 with Blurred Background Canvas`**), **Horizontal (`16:9`)**, **Square (`1:1`)**, and **Vertical Feed (`4:5`)**.
- **Dynamic OpenCV Face-Tracking Crop (`16:9` → `9:16`) & Podcast Split-Screen**:
  - Automatically follows human faces to keep the speaker centered in vertical `9:16` video:
    - **`👑 Dominant Subject (Largest Face)`**: Tracks the main person on screen.
    - **`🎯 Interactive Click-to-Track`**: Click directly on any person's face in the video preview to lock a glowing purple tracking reticle onto that specific subject.
    - **`👈 Left Person (Speaker 1)`** / **`👉 Right Person (Speaker 2)`** / **`👥 Center (Both Subjects)`**.
    - **`🎙️ Podcast Split-Screen (Stacked 9:16)`**: Automatically crops two speakers and stacks them top-and-bottom in a vertical `9:16` layout.
- **File Size (MB) Compression & Resolution Downscaling**:
  - Choose **`💎 High Quality`**, **`👑 Maximum Encoder Quality (Lossless)`**, **`Standard Web`**, or dedicated MB-reduction presets (**`Higher`**, **`Web`**, **`80%`**, **`85%`**, **`Extreme`**), or downscale dimensions to `1080p`, `720p`, `480p`, or `50%`.
- **Offline Subtitles & Local AI Translation**:
  - Transcribe any local video with **Whisper AI**, burn subtitles into the video or export an `.srt` file, and optionally translate subtitles offline into **English, Spanish, French, German, or Japanese** via `Llama 3.2 1B` / `Llama 3 8B`.
- **CapCut-Style Video Filters & Audio Effects**:
  - **Video Filters**: *Black & White*, *Sepia*, *Vintage Film*, *Cyberpunk Neon*, *Warm Golden Hour*, *Cool Cinema*, *Dramatic Contrast*, *Dreamy Soft Glow*, plus **Film Grain (`0–30`)**, **Sharpen (`0–2`)**, **RGB Glitch (`0–10`)**, and **Cinematic Vignette**.
  - **Audio Effects**: *Slowed + Reverb (TikTok)*, *Nightcore / High Pitch*, *Vocal Remover (Karaoke)*, *Echo*, *Concert Hall Reverb*, *Studio Vocal Polish*, *Lo-Fi / Vintage Radio*, *Bass Boost*, *Vocal Chorus*, **AI/FFT Noise Cancellation**, and **Voice Isolation & Clarity**.
- **Output Formats**:
  - **Video**: `MP4 (Universal H.264)`, `MP4 (4K / H.265 HEVC Master)`, `MOV (Apple ProRes 422 Studio)`, `MKV`, `GIF Animation`.
  - **Audio**: `MP3`, `WAV (Lossless PCM)` — convert any local video into an MP3 or WAV audio file in seconds.
  - **Images**: `PNG (Lossless)`, `JPG`.

---

### 3. 🛡️ AI Cleaner Tab (Metadata Sanitizer & Camera EXIF Simulator)

Cleanse AI-generated images, videos, and audio files in batch or folder mode while keeping your original files untouched.

- **Strip Embedded AI & Tracking Signatures**:
  - Purges embedded `SynthID`, `C2PA` manifests, `EXIF`/`XMP` tags, encoder strings, and container tracking payloads.
- **Visual & Bitstream Fingerprint Reset**:
  - Applies imperceptible microscopic pixel jitter, subtle edge cropping, and fresh bitstream encoding to neutralize platform re-compression flags.
- **Optional iPhone 15 Pro Hardware EXIF Injection**:
  - Enable **`Inject iPhone 15 Pro Hardware EXIF Metadata`** to write realistic mobile camera sensor tags (`Apple iPhone 15 Pro`, lens focal length, exposure metadata) into the output file.
- **100% Non-Destructive**:
  - Drag & drop multiple files or select an entire folder; sanitized copies are written to `Documents/Media Grabber/AI Cleaned/` with a live terminal log.

*(Note: Metadata cleaning removes container tags and re-encodes media; it cannot remove visible burned-in watermarks or guarantee bypass of all third-party classifiers.)*

---

### 4. 🎬 Captions Studio Tab (Creator Video Studio, Karaoke & Local Translations)

![Captions Studio 4-zone editor](assets/ui_captions.png)

A dedicated 4-zone desktop video editor for building music videos, lyric videos, and captioned Reels/Shorts from local videos or MP3/WAV songs.

- **Create Videos from a Song or Video**:
  - Start from any video clip or click **`🎵 Create from Song`** (`MP3`, `WAV`, `M4A`, `FLAC`, `OGG`) in **Portrait (`9:16`)**, **Square (`1:1`)**, or **Landscape (`16:9`)**.
  - Stitch up to **30 video/photo clips** on the storyboard with 2-row clip cards, per-clip speed (`0.25×–4×`), source-start offsets, **`✂️ Split at Playhead` (`Ctrl+B`)**, **`⚡ Cut to Beat`** (auto-snaps cuts to musical beats), and **`xfade` transitions** (*Dissolve*, *Fade to Black*, *Flash White*, *Slide*, *Zoom*, *Wipe*).
- **Integrated Free Stock Videos & Social Clip Grabber**:
  - Search **Mixkit HD Stock** (1,370+ free HD clips) and **YouTube Shorts / Google** directly inside the studio with **no API key needed**, or connect free **Pixabay** / **Pexels** keys, or paste any TikTok/Reel/Short URL to grab and append it directly to your sequence.
- **Visual FX, Audio Visualizer & AR Face-Snapping Stickers**:
  - Apply TikTok/Snapchat visual filters (*Beauty Glow*, *VHS 90s*, *Teal & Orange*, *Vaporwave*, *KiraKira*, *Fish-Eye*, *Film Noir*), B-roll Picture-in-Picture overlays, audio-reactive **Spectrum Bars / Waveform** visualizers, and emojis/custom PNG stickers with **OpenCV Face Snapping (`🎯 Snap to Face`)**.
- **Karaoke Timing & Reviewable Lyric Sync**:
  - Paste your own lyrics and choose **`Correct lyrics, keep timing`** or **`Sync lyrics to audio`** (powered by Whisper + `stable-ts`, supporting Greek, English, French, Korean, and mixed-language songs).
  - Review proposed changes before applying; uncertain lines, words stretched `> 4.0s` across instrumental gaps, and mixed-script lines are automatically flagged for listening checks.
  - Fine-tune word timings by dragging blocks on the waveform timeline, nudging with arrow keys, or typing exact timestamps, and combine **Karaoke Highlight**, **Cumulative Highlight**, **Active Word Pop (`115%`)**, and 60fps animations (*Typewriter*, *Pop*, *Fade*, *Slide Up*, *Zoom In*).
- **Offline AI Lyric Translation (`Qwen3-4B` & Ollama) & Shared Layout**:
  - Click **`Set up local translator (2.5 GB)`** to download and verify the official `Qwen3-4B-Q4_K_M.gguf` model locally (or use local Ollama) to translate lyrics with song context, custom glossaries, ambiguity notes, and automatic chorus reuse.
  - Export **Original**, **Translated**, or **Bilingual (Original + Translation)** videos (`MP4`), styled subtitles (`ASS`), or `SRT` with bundled open-license fonts (**Montserrat**, **Roboto**, **Noto Sans KR**, **Oswald**, **Lobster**, **Bangers**) and smart glyph fallback (`Roboto` for Greek, `Noto Sans KR` for Korean).

---

### 5. 🖼️ Gallery Tab (Media Library, Favorites & Lightbox Inspector)

Browse, preview, and manage all your downloaded, converted, and cleaned files in one visual library.

- **Instant Search & Category Filters**:
  - Filter by **`All Media`**, **`❤️ Liked Only`**, **`YouTube`**, **`Instagram`**, **`TikTok`**, **`Twitter`**, **`Conversions / Edits`**, or **`AI Cleaned`**, or search by filename in real time.
- **Full-Screen Lightbox Preview Modal**:
  - Click any video, image, or audio file to open the lightbox player with keyboard arrow navigation (`←` / `→`) and 1-click actions:
    - **`❤️ Like / Favorite`**: Save your best reference clips to the `Liked Only` filter.
    - **`📂 Folder`**: Reveal the exact file inside Windows Explorer.
    - **`↗️ Open File`**: Launch the file in your default Windows media player.
    - **`🌐 Visit Post`**: Jump directly back to the original TikTok, Instagram, or YouTube post URL in your browser.
    - **`✨ AI Prompt`**: Generate an on-demand AI visual scene prompt from any saved video or image.
    - **`🗑️ Delete`**: Safely send unwanted files to the Windows Recycle Bin.

---

### 6. 🕓 History Tab (Searchable Download Log & Song Recognition Archive)

Keep a permanent, searchable record of every link you have processed.

- **Complete Metadata Log**: Displays each download's title, platform icon, date/time, original source URL, and any **Shazam-identified song title & artist**.
- **Search & Quick Actions**: Filter history by title or URL, copy the original link, revisit the source post in your browser, re-queue a link with 1 click, or clear history.

---

### 7. ⋯ More Tools Menu: Kling Prep & Carousel Studio

Accessible from the **`⋯` (More Tools)** button in the top navigation bar:

- **🎞️ Kling Prep (Nano Banana → Kling Character Replacement Workflow)**:
  1. Pick a downloaded reference video or upload a local clip.
  2. Inspect an automatic **6-frame contact sheet** and click any candidate timestamp to recut the exact starting frame (`first_frame.png`) and matching trimmed reference video.
  3. Upload your AI influencer character image and generate a tailored **Nano Banana prompt** that instructs your image generator to replace the subject while preserving exact pose, camera framing, clothing, and lighting.
  4. Export a ready-to-use **`ZIP` bundle** (`reference_video.mp4`, `first_frame.png`, `influencer_image.png`, and `README.txt`).
- **🖼️ Carousel & Still Image Studio**:
  - Upload or select multiple photos, reorder slides via drag-and-drop, apply **`4:5`**, **`1:1`**, **`9:16`**, or **`16:9`** aspect ratios with fit/fill/blurred-pad framing, safe margins, rotation, visual filters, and multilingual text overlays, and export an ordered **`ZIP`** for Instagram or TikTok carousels.

---

### 8. 📊 Right Panel: Activity Hub, Task Queue & Live Console

Always visible on the right side of the main workspace:

- **Tasks Queue**: Shows real-time progress bars, download speeds, Shazam song matches, and instant action buttons on completed tasks (**`📂 Folder`**, **`▶ Play`**, **`📋 Copy Path`**, or **`↻ Retry`** on failed jobs).
- **Live Console**: Switch to the **`Live Console`** tab to view real-time streaming logs from `yt-dlp`, `FFmpeg`, `Whisper`, and the local Python engine.
- **Top System Bar**: Displays your active **GPU Hardware Encoder Badge** (`⚡ NVIDIA NVENC`, `Intel QSV`, `AMD AMF`, or `CPU`), **AI Engine Pack status**, and **In-App Update Checker**.

---

## 🚀 How to Install & Set Up Dependencies

### Option 1: 1-Click Windows Installer (Recommended for Most Users)

You do **not** need to install Python, Node.js, or FFmpeg manually when using the Windows installer — they are bundled inside.

1. Go to the [**GitHub Releases page**](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases/latest) and download **`AI-Influencer-Media-Grabber-v3.2.0-Setup.exe`**.
2. Run the installer. It installs into `%LOCALAPPDATA%\AI Influencer Media Grabber` and creates a **Desktop** and **Start Menu** shortcut (`AI Influencer Media Grabber`).
3. Double-click the shortcut to launch the app. All core features (Downloader, YouTube-to-MP3, Media Tools, Trimmer, Face-Tracking Crop, AI Cleaner, Kling Prep, Carousel Studio, Gallery, History, and Creator Studio video editing) work immediately out of the box.

---

### Option 2: Installing the Optional AI Engine Pack (For Offline Whisper, BLIP & Local LLMs)

To keep the main installer compact (~111 MB), heavy offline AI models (`PyTorch`, `Whisper`, `stable-ts`, `Transformers/BLIP`, and `llama-cpp-python`) are provided as an optional 1-click **AI Engine Pack**:

1. **From Inside the App (Easiest)**:
   - Click the **`✨ Install AI Engine`** badge in the top-right header bar of the app and click **Start Installation**.
   - The app automatically prepares `setuptools`/`wheel`, installs all required AI packages constrained to the core runtime, verifies every AI interface (`Whisper`, `stable-ts`, `Torch`, `BLIP`, `llama_cpp`) in a fresh process, and prompts you to restart.
2. **Or via Batch Script**:
   - Double-click `install_ai.bat` in the application folder.
3. **Optional Local Lyric Translator (`Qwen3-4B`, 2.5 GB)**:
   - After installing the AI Engine Pack, open **Captions Studio → Lyrics & AI → Translation workspace** and click **`Set up local translator (2.5 GB)`** to download and verify the pinned official `Qwen3-4B-Q4_K_M.gguf` model locally.

---

### Option 3: Running from Source (For Developers)

If you are cloning the repository and running from source on Windows:

#### Prerequisites
- **Python 3.13** (64-bit)
- **Node.js 26+** (used for media stream helpers and frontend tests)
- **Git**

#### 1. Clone & Install Core Dependencies
```powershell
git clone https://github.com/NextGenInfluencer/ai-influencer-media-grabber.git
cd ai-influencer-media-grabber

python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```
*(Note: `requirements.txt` includes `imageio-ffmpeg`, which provides a self-contained FFmpeg binary automatically.)*

#### 2. Install Optional AI Dependencies (Whisper, Alignment, BLIP, Llama.cpp)
```powershell
python -m pip install setuptools wheel
python -m pip install --no-build-isolation -c requirements.txt --only-binary=llama-cpp-python -r requirements-ai.txt
python -m assets.ai_setup
```

#### 3. Launch the Application
```powershell
python app_local.py
```
Or double-click **`run.bat`** (or **`launch-silent.vbs`** for background windowless launch).

#### 4. Run Automated Test Suites & Build the Windows Installer
```powershell
python -m unittest discover -s tests -v
node tests/test_stream.js
node tests/test_caption_timing.js
node --check static/captions.js

# Build portable staging directory + Inno Setup 6 installer (dist/AI-Influencer-Media-Grabber-v3.2.0-Setup.exe)
python build_staging.py
```

---

## 🔄 Updating & Data Safety

- **User Data Location**: Your downloaded media, history (`history.json`), liked items, custom fonts (`static/fonts/custom/`), and Creator Studio projects (`Caption Projects/`) live in `Documents/Media Grabber` and are **never overwritten or deleted** during updates.
- **In-App Updater**: The header badge automatically checks GitHub Releases for new versions. Code-only updates can be applied in 1 click; releases that update Python/AI dependencies will safely prompt you to download and run the latest `Setup.exe` installer.
- **Version History**: See [RELEASE_NOTES.md](RELEASE_NOTES.md) and [CHANGELOG.md](CHANGELOG.md).
