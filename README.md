# AI Influencer Media Grabber & Creator Studio

![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows)
![Local Studio](https://img.shields.io/badge/Studio-100%25%20Local-0a84ff?style=for-the-badge)
![GPU Accelerated](https://img.shields.io/badge/Encoding-NVENC%20%2F%20QSV%20%2F%20AMF%20%2F%20CPU-30d158?style=for-the-badge)

**An all-in-one Windows desktop application for downloading high-quality social reference media, editing videos and photos, and producing music and lyric videos with karaoke timing, bilingual translations, and visual effects for Reels, TikTok, and YouTube Shorts.**

Save reference clips and carousels, prepare character-replacement assets for Nano Banana and Kling, or build full song videos from scratch with multi-clip sequences, synchronized karaoke lyrics, and local AI translations.

[Download Latest Windows Installer](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases/latest) · [Release Notes](RELEASE_NOTES.md) · [Changelog](CHANGELOG.md) · [Lyrics & Translation Guide](docs/creator-lyrics-guide.md)

---

## A Look Inside

<div align="center">
  <img src="assets/ui_downloader.png" width="49%" alt="Studio Downloader: reference links and processing options" />
  <img src="assets/ui_converter.png" width="49%" alt="Media Tools: video conversion, cropping and trimming" />
  <br>
  <img src="assets/ui_gallery_preview.png" width="49%" alt="Output Gallery: browse saved media and revisit source posts" />
  <img src="assets/ui_cleaner.png" width="49%" alt="Metadata cleanup tools" />
</div>

---

## Core Capabilities

### 1. Reference Media Downloader
- **Multi-Platform Grabbing**: Download videos from TikTok, YouTube, YouTube Shorts, Instagram Reels, and other supported sites, plus Instagram photos and multi-slide carousels (with automatic `gallery-dl` fallback).
- **Best Source Quality**: Selects the highest available source stream quality, with options to extract MP3 audio, capture the first video frame as a reference image, or transcode to standard H.264 for editing compatibility.
- **Library & Source Tracking**: Keeps source-post links alongside downloaded files in the **Output Gallery** with 1-click actions to play, open in Windows Explorer, copy file paths, or revisit the original post.

*Note: TikTok downloads use the unwatermarked source stream when available; watermarks already burned into uploaded source footage cannot be removed. Private or restricted posts may require browser cookies.*

---

### 2. Creator Video Studio (Music Videos & Multi-Clip Storyboards)

![Captions editor with aligned lyrics and live font styling](assets/ui_captions.png)

- **4-Zone Desktop Workspace**: Work in a unified studio layout with a Left Tool Dock (`🎬 Media & Clips`, `🌐 Free Videos`, `📝 Lyrics & AI`, `✨ Filters & FX`, `🎵 Audio & Voice`, `🎭 Stickers`, `🎞️ Canvas & PiP`), responsive aspect-ratio Center Stage (`9:16` Portrait, `1:1` Square, `16:9` Landscape), Right Inspector, and Bottom Multitrack Timeline.
- **Create Video from a Song**: Start with any `MP3`, `WAV`, `M4A`, `FLAC`, or `OGG` audio track (up to 20 minutes), trim the song range, adjust start delay and fades, and combine it with a solid colour, uploaded photo/video, or multi-clip sequence.
- **Multi-Clip Sequence Storyboard**:
  - Stitch up to **30 video or photo clips** with structured 2-row clip cards, source-start offsets (`Source start (s)`), per-clip playback speed (`0.25×` slow-motion to `4×` hyper-lapse), and sequence Undo/Redo.
  - **Split at Playhead (`Ctrl+B`)** and **Cut to Beat (`⚡ Cut to Beat`)** to snap cuts automatically to musical transients.
  - **Cinematic Transitions**: Smooth FFmpeg `xfade` transitions between cuts (*Dissolve*, *Fade to Black*, *Flash White*, *Slide Left/Right*, *Zoom / Circle Crop*, *Wipe Left/Right*).
- **Built-In Free Stock & Social Clip Grabber**:
  - Search **Mixkit HD Stock** and **YouTube Shorts / Google** directly inside the editor with no API key required, or connect free **Pixabay** and **Pexels** keys.
  - Paste a TikTok, Instagram Reel, or YouTube Short URL into the studio's **Grab Clip** box to download and append it directly to your sequence.
- **Non-Destructive Visual FX, Audio FX & Stickers**:
  - **Video Filters & Grading**: 1-click presets (*TikTok Beauty Glow*, *VHS 90s*, *Teal & Orange*, *Vaporwave Neon*, *KiraKira*, *Fish-Eye*, *Film Noir*, *Cyberpunk*, *Vintage*, *Warm*, *Cool*, *Dreamy*) plus brightness, contrast, saturation, vignette, film grain, sharpen, and chromatic RGB shift.
  - **Audio Processing & Visualizer**: Voice isolation, noise cancellation, studio vocal/reverb/echo/bass-boost effects, background audio mixing with speech ducking, and audio-reactive **Spectrum Bars** or **Waveform** visualizers.
  - **B-Roll PiP & AR Face-Snapping Stickers**: Picture-in-Picture B-roll overlays, intro title cards, custom PNG/WebP/GIF stickers, reaction emojis, and local OpenCV face detection (`🎯 Snap to Face`) to position props on the head, eyes, or face center.
- **Per-Project Draft Recovery**: Pending uploads, sticker selections, stock notices, and unsaved lyric drafts are isolated per project in browser `IndexedDB` (up to 512 MB), surviving dialog reopens, project switches, page reloads, and failed renders.

---

### 3. Multilingual Lyrics, Karaoke & Local AI Translation

- **Preserve Your Wording**:
  - **Correct lyrics, keep timing** maps your pasted lyrics onto existing subtitle timings without altering your spelling or line breaks.
  - **Sync lyrics to audio** runs local Whisper + `stable-ts` forced alignment across supported languages (including Greek, English, French, Korean, and mixed-language modes such as *Greek + English* and *Korean + Greek*).
  - **Review Before Apply**: Every alignment or lyric correction prepares a side-by-side proposal with per-line audio auditioning. Uncertain segments, words stretched `> 4.0s` across instrumental breaks, and same-line mixed scripts are automatically flagged (`needs review`) so you can verify them by ear. Interrupted alignments can resume from saved section checkpoints.
- **Interactive Word-Timing & Karaoke Controls**:
  - Edit word start/end times numerically, drag or resize word blocks on the lane, or nudge boundaries with keyboard arrow keys (`±0.02s`).
  - Combine **Highlight current word (Karaoke)**, **Cumulative highlight**, **Active word pop (115% scale)**, and 60fps entrance animations (*Typewriter*, *Pop Entrance*, *Smooth Fade*, *Slide Up*, *Zoom In*) with instant live preview and 1-click viral caption presets (*Beast Pop*, *Cyberpunk*, *Frosted Vlog*, *Sunset Glow*).
- **Local AI Lyric Translation Workspace**:
  - Maintain separate per-language translation tracks with `approved`, `locked`, and `stale` states (editing original lyrics automatically marks translations as `stale` for review).
  - Click **Set up local translator (2.5 GB)** to download and verify the pinned official `Qwen3-4B-Q4_K_M.gguf` model locally (with SHA-256 checksum, disk-space, and cancellation protection), or connect an optional local **Ollama** model.
  - Provide **Song context** and a **Glossary** for idioms, metaphors, and names; repeated chorus lines automatically reuse approved/generated wording across chunks and resumed jobs.
  - Export **Original only**, **Translation only** (requires approval for every line), or **Bilingual (original + translation)** captions to burned-in **MP4**, styled **ASS**, or **SRT**.
- **Shared Layout & Bundled Multilingual Fonts**:
  - Shared layout engine calculates line wrapping, line/letter spacing, box width, original-translation gap, and animated rounded background plates across both preview and export, automatically fitting overlong words and unspaced Korean phrases without altering karaoke tokens.
  - Includes bundled open-license fonts (**Montserrat**, **Roboto**, **Noto Sans KR**, **Oswald**, **Lobster**, **Bangers**) and supports custom `.ttf`/`.otf` font uploads stored safely in your user-data folder.
  - **Smart Script Fallback**: Automatically falls back to bundled **`Roboto`** for Greek and **`Noto Sans KR`** for Korean when using decorative Latin fonts, keeping Greek words unified without splitting mid-word on math symbols (`μ`, `π`, `Δ`, `Ω`).

---

### 4. Media Tools, Kling Prep, Carousel Studio & Metadata Cleaner

- **Media Tools & GPU Encoding**: Convert formats, trim, crop/resize, apply vertical face-tracking framing, extract frame sequences, or create GIFs. Video exports automatically detect and use hardware encoding (**NVIDIA NVENC**, **Intel QuickSync**, **AMD AMF**) with automatic software CPU fallback (`libx264` / `libx265`) and a manual **Use CPU** override.
- **Nano Banana → Kling Prep**: Extract a reference video, `first_frame.png`, and a 6-frame contact sheet to select the best starting timestamp, paired with scene-description prompts that instruct your image tool to preserve pose, framing, clothing, and lighting.
- **Carousel & Still Image Studio**: Reorder slides, apply `4:5`, `1:1`, `9:16`, or `16:9` canvas presets, safe margins, rotation, and multilingual text overlays, and export an ordered ZIP.
- **Metadata Cleaner**: Strip embedded EXIF/container metadata tags and create clean processed copies (*does not remove visible watermarks or guarantee prevention of AI detection*).

---

## Installation & Updates

### Windows Installer (Recommended)
1. Go to [Releases](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases/latest) and download the latest `AI-Influencer-Media-Grabber-vX.Y.Z-Setup.exe`.
2. Run the installer and launch **AI Influencer Media Grabber** from your Desktop or Start Menu shortcut.
3. *(Optional)* Click **Install AI Engine** in the top bar when you want local Whisper transcription, `stable-ts` lyric alignment, BLIP vision analysis, or local Qwen3 lyric translation, then restart the app.

The Windows installer bundles an isolated Python 3.13 and Node runtime plus FFmpeg. Your downloads, caption projects, and custom fonts are stored in `Documents/Media Grabber` and are preserved across updates.

### Running from Source
Use Python 3.13 and Node 26:
```bash
python -m pip install -r requirements.txt
python app_local.py
```
For optional AI features, run `install_ai.bat` or install `requirements-ai.txt` constrained by `requirements.txt` into the same Python environment. Run tests with:
```bash
python -m unittest discover -s tests -v
node tests/test_stream.js
node tests/test_caption_timing.js
node --check static/captions.js
```

### Updating
The in-app updater checks GitHub Releases and applies code-only updates automatically. When a release updates Python or AI dependencies, the updater safely prompts you to run the full `Setup.exe` release installer so your environment remains consistent. See [Release Notes](RELEASE_NOTES.md) and [Changelog](CHANGELOG.md) for version details.
