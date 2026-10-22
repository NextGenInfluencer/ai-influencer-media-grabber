# AI Influencer Media Grabber

![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows)
![Local editing](https://img.shields.io/badge/Editing-Local-f472b6?style=for-the-badge)

**A Windows desktop toolkit for downloading reference media, editing videos and photos, and creating captioned content for Reels, TikTok and YouTube Shorts.**

Save a reference clip, extract its first frame, prepare a character replacement for Nano Banana and Kling, or work on your own footage. The app brings downloading, conversion, a media library, and editable captions into one place.

[Download the latest Windows release](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases/latest) · [Release notes](RELEASE_NOTES.md) · [Implementation details](IMPLEMENTATION_NOTES.md)

## A look inside

<div align="center">
  <img src="assets/ui_downloader.png" width="49%" alt="Studio Downloader: reference links and processing options" />
  <img src="assets/ui_converter.png" width="49%" alt="Media Tools: video conversion, cropping and trimming" />
  <br>
  <img src="assets/ui_gallery_preview.png" width="49%" alt="Output Gallery: browse saved media and revisit source posts" />
  <img src="assets/ui_cleaner.png" width="49%" alt="Metadata cleanup tools" />
</div>

*Studio screenshots show the earlier interface; available controls can differ by version.*

## What you can do

### Download reference media

- Download videos from TikTok, YouTube and YouTube Shorts, Instagram Reels, and other sites supported by the download engines.
- Save Instagram photos and carousel media, with a gallery-dl fallback where applicable.
- Choose the best available source quality, including higher-resolution YouTube streams when available. The source platform determines the maximum quality.
- Extract audio to MP3, or save the first video frame as an image.
- Optionally convert to standard H.264 for import compatibility. This re-encodes the video; it does not improve character recognition or recover missing detail.
- Keep source-post links alongside your downloads and revisit posts from the gallery.

TikTok downloads use the available source stream, which can avoid the additional watermark on TikTok's normal downloaded copy. Watermarks already embedded in the source cannot simply be removed. Private, restricted or changed platform endpoints may require cookies or may not be available.

### Edit your own videos and pictures

Use **Media Tools** for conversion, trimming, crop/resize, vertical framing, blurred padding, GIF creation, audio extraction and frame sequences. Output choices include common sharing formats and higher-quality editing formats. Face-tracking framing options help turn suitable footage into vertical clips.

The **Output Gallery** keeps downloaded and generated media together, with previews, file actions and prompt extraction. Local uploads can be used without downloading anything first.

### Prepare Nano Banana → Kling references

Extract a first frame, replace the person with your influencer in your image tool, then use the matching reference video in Kling. The prompt helper describes the scene while instructing the image tool to preserve pose, framing, clothing and lighting. **Kling Prep** helps prepare compatible, matching video/frame outputs; it does not run Kling or guarantee generation quality.

### Captions & Lyrics

![Captions editor with aligned lyrics and live font styling](assets/ui_captions.png)

Open **Captions & Lyrics** from the Studio navigation:

1. Upload a video or choose one from the media library.
2. Auto-transcribe with the optional AI Pack, paste lyrics, or import SRT/LRC.
3. Edit the words and timing on the waveform timeline. Move or resize caption blocks, split/merge lines, loop a line, adjust playback speed, and undo edits.
4. Choose a font, colours, size, outline, position, background and word-by-word highlighting. Watch changes in the live preview.
5. Use **Render 5-second check** to see actual export typography, then export a captioned H.264 MP4 or an SRT file.

Projects autosave under `Caption Projects` in your media library. SRT carries text and timing, not fonts or effects. Automatic transcription needs review, especially for songs. Browser text layout is an approximation; the rendered check shows the final result.

### Karaoke from your existing SRT

Import your SRT and click **Add karaoke timing to all subtitles**. This analyses each line's audio and adds word timings while keeping your text, line breaks, line start/end times and style. Enable **Highlight the current word** to see the result.

The alignment-language selector supports English, French, Korean, Greek, Spanish, German, Italian, Portuguese, Japanese, Chinese, Arabic, Hindi, Russian and Turkish. Choose **Detect per line**, **English + French**, **Korean + English** or **English + French + Korean** for mixed songs, or override a single language and **Retry karaoke for this line**. Ambiguous scripts use local audio language detection; short sung lines can be misidentified. Korean highlighting follows space-separated words. For untimed pasted mixed lyrics, sync matching language sections; these mixed modes apply to the existing-subtitle karaoke action. Mixed-language and unusually short timings are flagged. **Next line to review** visits missing or flagged timings; listen, edit the word boundaries and mark them reviewed. Flags are timing heuristics, not guaranteed accuracy scores.

Failed lines retain their earlier words/timings. **Estimate missing timings** is an explicit approximate fallback, labelled for review. A cancelled operation preserves saved captions; **Restore previous karaoke version** restores the captions from before the last completed karaoke operation, including after reopening the project. Undo also works in the editing session. Long individual lines over 60 seconds need splitting before alignment.

### New in v3.1.2 (Permanent Fix for Desktop Spontaneous Closing)

- **Eliminated Spontaneous Desktop Shutdowns**: The background heartbeat watchdog thread has been completely disabled by default. The local Python server now runs continuously, eliminating unexpected closures when the window is minimized, when Windows is locked, or during Chromium background timer suspension.
- **Opt-in Headless Watchdog**: Watchdog is now strictly opt-in via `--enable-watchdog` or `MEDIA_GRABBER_ENABLE_WATCHDOG=1` with a safe 24-hour timeout (86,400s).

### New in v3.1.1 (Dynamic Lyric Animations & Instant Live Preview)

- **Live Animation Preview on Selection**: Selecting any animation style (*Typewriter*, *Pop Entrance*, *Smooth Fade*, *Slide Up*, *Zoom In*) plays an instant 60fps preview directly on the canvas, even while the video is paused.
- **1-Click Preview Control**: Dedicated `▶ Preview` action button next to the Animation dropdown for instant replaying.
- **Typewriter + Karaoke Word Timing Integration**: Full progressive character typing and word revelation synchronized with karaoke highlights and active word popping.
- **Pro Spring Easing**: Enhanced entrance curves with natural overshoot and fluid acceleration.
- **Exported Subtitle Parity**: Full ASS export synchronization so rendered MP4s display the exact typewriter motion.

### New in v3.1.0 (Watchdog Keepalive Fix + Production Stability Suite)

- **Rock-Solid Background Watchdog & Multitasking Keepalive**: Eliminated unexpected app shutdown caused by Chromium background tab timer throttling. The idle tolerance is increased to 300 seconds (5 minutes), combined with reactive `visibilitychange` and `focus` event listeners for instant session keepalive whenever the user switches back. Removed the aggressive 4-second shutdown on page navigation.
- **Hardware-Accelerated Video Encoding (NVENC / QSV / AMF / Apple VideoToolbox):** Automatic GPU acceleration probe detects host graphics capabilities on startup, using native NVENC (NVIDIA), QuickSync (Intel), AMF (AMD), or Apple VideoToolbox for ultra-fast exports and trimming, with zero-configuration automatic software CPU fallback (`libx264`/`libx265`).
- **Live GPU Telemetry Badge:** Dedicated header status indicator displaying the active hardware encoder engine (e.g. `⚡ NVIDIA NVENC`, `⚡ Intel QSV`, `⚡ AMD AMF`) with real-time health feedback.
- **Apple macOS Pro Acrylic Sheet Dialogs:** Complete redesign of secondary modals (`browserModal`, `mediaPreviewModal`, `aiInstallModal`, `appUpdateModal`) using frosted glass backdrop blur (28px - 32px), translucent obsidian surfaces, and Apple System Blue `#0071e3` tactile action buttons.
- **Activity Hub Direct Actions:** Completed queue tasks now feature instant 1-click action pills: `📂 Open Folder` (reveals in Explorer), `▶ Play` (launches system media player), and `📋 Copy Path` (copies absolute file path to clipboard). Failed items feature an instant `↻ Retry` button.
- **Timeline Pro Edge Trimming & Storyboard Sequence Control:** Precision drag-to-trim edge handles (`||`) on timeline cue blocks with hover glow feedback and Apple Blue highlights; tactile storyboard reordering controls (`◀` / `▶`) on sequence clip cards.
- **Streamlined Pro Navigation:** Clean, uncluttered segmented top bar focusing on primary workflows (Downloader, Media Tools, AI Cleaner, Captions Studio, Gallery, History), with Kling Prep and Carousel Studio tucked into a sleek secondary tools overflow menu.

### New in v3.0.0 (GPU Hardware Acceleration Engine + Apple Pro Acrylic Studio Suite)

- **Hardware-Accelerated Video Encoding (NVENC / QSV / AMF / Apple VideoToolbox):** Automatic GPU acceleration probe detects host graphics capabilities on startup, using native NVENC (NVIDIA), QuickSync (Intel), AMF (AMD), or Apple VideoToolbox for ultra-fast exports and trimming, with zero-configuration automatic software CPU fallback (`libx264`/`libx265`).
- **Live GPU Telemetry Badge:** Dedicated header status indicator displaying the active hardware encoder engine (e.g. `⚡ NVIDIA NVENC`, `⚡ Intel QSV`, `⚡ AMD AMF`) with real-time health feedback.
- **Apple macOS Pro Acrylic Sheet Dialogs:** Complete redesign of secondary modals (`browserModal`, `mediaPreviewModal`, `aiInstallModal`, `appUpdateModal`) using frosted glass backdrop blur (28px - 32px), translucent obsidian surfaces, and Apple System Blue `#0071e3` tactile action buttons.
- **Activity Hub Direct Actions:** Completed queue tasks now feature instant 1-click action pills: `📂 Open Folder` (reveals in Explorer), `▶ Play` (launches system media player), and `📋 Copy Path` (copies absolute file path to clipboard). Failed items feature an instant `↻ Retry` button.
- **Timeline Pro Edge Trimming & Storyboard Sequence Control:** Precision drag-to-trim edge handles (`||`) on timeline cue blocks with hover glow feedback and Apple Blue highlights; tactile storyboard reordering controls (`◀` / `▶`) on sequence clip cards.
- **Streamlined Pro Navigation:** Clean, uncluttered segmented top bar focusing on primary workflows (Downloader, Media Tools, AI Cleaner, Captions Studio, Gallery, History), with Kling Prep and Carousel Studio tucked into a sleek secondary tools overflow menu.

### New in v2.8.1 (Apple macOS Pro UI/UX Overhaul + TikTok/Snapchat Suite)

- **TikTok & Snapchat Signature Aesthetic Filters (1-Click Presets & 0ms Live Preview):** Instantly apply iconic social media visual presets with real-time CSS stage preview and native FFmpeg export:
  - **✨ TikTok Beauty Glow:** Soft-skin porcelain smoothing and luminous highlight bloom.
  - **📼 VHS 90s Camcorder:** Chromatic RGB aberration, retro tape noise, and scanline texture.
  - **🌅 Teal & Orange Cinematic:** Deep teal shadows contrasted with warm peach skin tones.
  - **💖 Vaporwave Neon:** Y2K electric pink and magenta punch with hyper-saturated anime colors.
  - **💎 KiraKira / Bling Sparkle:** Specular highlight pop and glitz starburst highlights.
  - **🐟 Fish-Eye Bubble Lens:** Convex wide-angle lens distortion for skate videos and meme POVs.
  - **🎞️ Film Noir / Gotham Dark:** Crushed moody blacks and desaturated silver tones.
- **OpenCV Face Snapping for Stickers & Props (🎯 Snap to Face):** Local computer vision face detection finds subjects in the current video frame and snaps stickers/props to the 👑 Head / Crown, 🕶️ Eyes / Shades, or 🎭 Face Center with zero cloud subscriptions or API keys.
- **Sub-Millisecond Float Precision Sanitization & Auto-Clamping:** Resilient boundary tolerance prevents floating-point rounding errors when aligning lyrics, timing words, or editing cue blocks.
- **Unified Preview & Export Geometry:** Perfectly aligned center-anchored coordinates between web stage preview and FFmpeg sticker overlay.

### New in v2.7.2 (Cut-to-the-Beat, Per-Clip Speed & Sticker Overlays)

- **Cut-to-the-Beat / Auto Beat-Drop Snapping (`⚡ Cut to Beat`):** Analyze audio transients and snap all clip cuts directly to musical beat drops with 1 click for rhythmic TikTok and Reels videos.
- **Per-Clip Speed Ramping & Slow-Mo (0.25× to 4×):** Individual speed controls on each clip in the sequence storyboard with pitch-corrected audio and slow-motion video fluidity.
- **Stickers, Emojis & Transparent Graphic Overlay Track:** Dedicated Stickers pane with 1-click reaction emojis (`🔥`, `💃`, `👑`, `✨`, `💯`, etc.), custom transparent PNG/GIF/WebP file uploads, timing, X/Y placement, scaling, opacity, and entrance animations (`pop`, `fade`, `slide`).

### New in v2.7.1 (Split Clip, Custom Font Upload, 60fps/4K & Audio Badges)

- **Split Clip at Playhead (`Ctrl+B` / Split Clip Button):** Instantly cut any video or photo clip in the sequence at the current playhead position into two adjacent segments with millisecond precision, keeping all lyrics and surrounding clip timings locked.
- **Custom Font Upload / User Font Import (`.ttf` / `.otf`):** Upload your own TrueType or OpenType typography with magic-byte validation, 0ms live web preview via dynamic `@font-face` injection, and automatic bundling into FFmpeg ASS libass exports.
- **Advanced Export Quality & Framerate Presets:** Export with smooth **1080p 60fps** (CRF 17, 320k audio) and **4K Ultra HD 2160p** (CRF 15 studio master) for high-end cinematic vertical and horizontal video.
- **Timeline Audio Indicators:** Visual audio badges (`🔊`/`🔇`) on sequence clip blocks in the bottom timeline for instant audio status verification.

### New in v2.7.0 (Video Transitions, Non-Destructive Effects & Motion Presets)

- **CapCut-style Video Transitions Between Multi-Clip Cuts:** Add smooth cinematic transitions between cuts in multi-clip sequences (`Dissolve / Crossfade`, `Fade to Black`, `Flash White`, `Slide Left`, `Slide Right`, `Zoom / Circle Crop`, `Wipe Left`, `Wipe Right`) with customizable duration (0.1s to 2.0s) and frame-accurate FFmpeg `xfade` chaining.
- **100% Non-Destructive Reversible Video Filters & Visual FX:** Effects never permanently double-bake into base composition videos (`bake_fx=False`). Switching filters or resetting to `None` immediately restores untouched original colors with 0ms GPU-accelerated CSS preview and dynamic single-pass FFmpeg export.
- **Multi-Clip Background Audio Mixing with Silence Fallback:** Multi-clip video sequences preserve original audio tracks mixed under the main song with volume and speech ducking controls, with automatic stereo silence synthesis (`anullsrc`) for photos or muted clips.
- **Animated Caption & Title Card Motion Presets:** Dynamic `Zoom In` and character-by-character `Typewriter` reveal animations synchronized across both live canvas player and exported ASS subtitles.

### New in v2.6.1

Fixed the Creator Studio clip grabber, added cancellable download/search workers and safer URL handling, and corrected long-song clip cycling. See [release notes](RELEASE_NOTES.md).

### New in v2.6.0 (CapCut-Style Creator Studio)

- **Sync pasted lyrics to audio & transcription correction:** keeps your supplied text and line breaks, with editable word timings. Choose **Correct transcription with my lyrics** to match your pasted lyrics directly to existing transcription line timings, or **Sync lyrics to audio** to run audio alignment using local Whisper with stable-ts. Pasted lyrics are auto-saved locally as a draft. Standalone Suno labels such as `[Verse]` are ignored; repeated sung lines must still be included. If individual words have invalid timing, usable timings are retained and uncertain gaps are estimated and flagged for review. The prior captions are retained as a restore point.
- **Create video from a song:** start with MP3, WAV, M4A, FLAC or OGG. Choose portrait, square or landscape; use a colour, uploaded photo/video or a library background. Short video backgrounds loop and fill the frame with a centre crop. The song replaces background audio.
- **Audio-reactive spectrum & waveform visualizer:** add animated vertical EQ **Spectrum Bars** or a **Waveform** at the bottom, centre or top of your video with customizable height, sensitivity and colour, rendered with matching geometry in live preview and final export.
- **Bundled multilingual Google Fonts & 1-click presets:** Montserrat, Roboto, Noto Sans KR, Oswald, Lobster and Bangers (with open-font licenses) work locally in preview and export with Greek, Korean and French coverage. Style captions with **Cumulative karaoke**, **Active word pop (115% scale)**, **High-contrast boxed captions**, and 1-click music-video presets (**Neon Karaoke**, **Cinematic Clean**, **Bold Pop**, **Minimalist Lyric**).
- **Integrated Free Videos, Mixkit HD Stock, YouTube Shorts Search & Social Clip Grabber:** browse **🔥 Mixkit HD Stock** (1,370+ free HD dance & aesthetic videos) and **📱 YouTube Shorts / Google** directly inside the studio with **no API key required**, or connect **Pixabay** / **Pexels** API keys. Paste any **TikTok, Instagram Reel, or YouTube Short URL** into the built-in **Grab Clip** box to download without watermark and append directly to your music video sequence, or use the 1-click Dance & Vibe category chips (**💃 Dance**, **🔥 Street / Hip-Hop**, **🪩 Club & Party**, **💃 Modern Dance**, **✨ Neon Aesthetic**, **🌆 Night Drive**, **🎤 Concert / DJ**, **🌊 Sunset Vibe**).
- **CapCut-style 4-Zone Studio & Multi-Clip Video Sequence Storyboard:** work in a single-screen desktop studio with a Left Icon Dock (`🎬 Media & Clips`, `🌐 Free Videos`, `📝 Lyrics & AI`, `✨ Filters & FX`, `🎵 Audio & Voice`, `🎞️ Canvas & PiP`), Center Video Stage, Right Inspector, and Bottom Multitrack Timeline — without popup modal dialogs. Stitch up to **30 video or photo clips** into a multi-clip sequence, reorder clips (`←`/`→`), split your song evenly (`0s Auto`) or cycle clips every N seconds (`10s each`), and apply CapCut-style **Video Filters** (`B&W`, `Sepia`, `Vintage`, `Cyberpunk`, `Warm`, `Cool`, `Dramatic`, `Dreamy`), **Visual FX** (`Vignette`, `Film Grain`, `Sharpen`, `Chromatic Glitch`), and **Audio FX** (`Noise Cancellation`, `Voice Isolation`, `Echo`, `Concert Hall Reverb`, `Studio Vocal`, `Lo-Fi Radio`, `Bass Boost`, `Chorus`).
- **Multitrack overlays, keyframes & quality presets:** add B-roll / Picture-in-Picture overlays, intro title cards, keyframe pan/zoom, video fade transitions, brightness/contrast/saturation grading, background speed adjustments, automatic background audio ducking, and choose between **Fast Proxy / Draft (720p)**, **Standard HD (1080p)**, and **Studio High Quality (CRF 15 · 320 kbps)** exports.
- **Kling contact sheets & Carousel Studio:** inspect a 6-frame contact sheet and click any candidate timestamp to re-cut your Kling reference start alongside `first_frame.png`, or open the **Carousel & Still Image Studio** to reorder slides, apply 4:5 / 1:1 / 9:16 / 16:9 canvas presets, safe margins, rotation and multilingual text overlays, and export an ordered ZIP.

Song creation and lyric alignment support up to 20 minutes per operation. Use only the lyrics for the selected audio section. Existing captions are preserved if alignment fails or is cancelled. Manual estimates remain available without AI.

### Editable background and audio composition (source)

Open a song/video project and select **Background & audio → Edit composition**. Replace a background from an upload or your library without losing captions, word timings or style. Choose portrait/square/landscape, fit or fill, horizontal/vertical focus, blur, dimming, tint and slow zoom. Video backgrounds can loop or hold their final frame; still images last for the composition.

Trim the song, delay its start, adjust volume and fades, and optionally mix the background video's audio (muted by default). Lyrics follow changes to the song's source trim/delay. Lines outside the range are removed from that version; cut lines keep their text but lose word timings and are flagged for review. Replacing a song preserves captions and flags them so you can check synchronization.

**Apply & preview** renders a synchronized base and preview using the same composition specification. Seeking, playback speed and lyric looping then use that single prepared timeline. This step is not an instant multitrack preview; caption styling remains live. Use **Restore previous composition** to recover the prior composition and captions, or **Duplicate project** before exploring alternatives.

Projects retain original assets and a versioned composition schema (assets, tracks, clips, source offsets, transforms and text style). Legacy projects remain readable and receive a pre-migration JSON backup when first saved. Missing media is reported; upload its original file in the composition dialog to relink it. Captions autosave; **Recover unsaved captions** offers this browser's saved draft after an interrupted edit. Composition settings have a local draft too; file selections must be chosen again after restart. Generated versions are retained, so repeated changes require additional disk space.

### Optional AI tools and metadata cleanup

The AI Pack enables Whisper transcription, BLIP image descriptions and optional local language-model features. Model files require additional downloads and storage. Music identification uses an online service.

Metadata tools can clean embedded tags and create processed copies. They do **not** guarantee removal of visible/invisible watermarks or prevention of AI detection.

## Install and launch

### Windows installer

1. Open [Releases](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases).
2. Download the latest `Setup.exe`, run it, and launch the desktop shortcut.
3. Enable the optional AI Pack when you need transcription or image analysis.

The installer bundles the core runtime. You do not need a separate Python installation for that copy. Your media library normally lives in `Documents/Media Grabber`.

### Run from source

Use Python 3.13 and Node 26 for the supported build/test configuration. Install `requirements.txt`, then run `app_local.py`, or use `run.bat` on Windows. `create_shortcut.bat` creates a shortcut; `launch-silent.vbs` opens the app from the folder containing that launcher.

For AI features, install `requirements-ai.txt` into the **same environment** used by the launcher. Existing AI installations need the updated pack for automatic lyric alignment. Restart after installing it.

**A source shortcut and an installed desktop shortcut can point at different app copies.** After updating files, fully exit the running app and reopen the matching shortcut. The launcher reuses an already-running local server.

## Updates

The in-app GitHub updater checks published releases and validates staged changes before applying them. Updates that change dependencies require the release installer. In particular, use the v2.5.0 installer when upgrading an older installed copy to the first Captions & Lyrics release. New source features listed above are not available through the published v2.5.0 installer yet.

| Version | Highlights |
| --- | --- |
| v3.1.2 | Permanent fix for auto-shutdown / crash: disabled spontaneous watchdog timeout, rock-solid desktop session persistence |
| v3.1.1 | Dynamic lyric animations, instant 60fps live animation preview, typewriter + karaoke sync, pro spring easing |
| v3.1.0 | Background watchdog keepalive fix (no unexpected closing), GPU Hardware Acceleration (NVENC/QSV/AMF), macOS acrylic sheet modals, Activity Hub direct actions |
| v3.0.0 | GPU Hardware Acceleration (NVENC/QSV/AMF), macOS acrylic sheet modals, Activity Hub direct actions (Play/Folder/Copy/Retry), Timeline Pro edge trimming handles |
| v2.8.1 | Apple macOS Pro UI/UX overhaul, 1-click paste & open, shortcuts modal, timeline zoom, TikTok & Snapchat filters |
| v2.8.0 | TikTok & Snapchat aesthetic filters, OpenCV AR face tracking & auto-snapping, float precision auto-clamping |
| v2.7.2 | Cut-to-the-beat auto snapping, per-clip speed ramping (0.25x to 4x), stickers & emoji graphic overlay track |
| v2.7.1 | Split clip at playhead (Ctrl+B), custom font upload (.ttf/.otf), 1080p 60fps & 4K UHD presets, timeline audio indicators |
| v2.7.0 | Video transitions between multi-clip cuts, 100% reversible non-destructive effects, multi-clip background audio mixing and caption motion presets (Zoom In, Typewriter) |
| v2.6.1 | Clip-grabber repair, download/search safeguards, cancellation and long-song cycling fixes |
| v2.6.0 | CapCut-style 4-zone studio, Multi-Clip Video Sequence Storyboard, Free Mixkit HD Stock & YouTube Shorts search (no API key needed), direct TikTok/Reel/Short clip grabber, 1-click dance category chips, multilingual batch karaoke, CapCut video filters & audio effects (noise cancellation, voice isolation, echo/reverb), Carousel Studio & Kling contact sheets |
| v2.5.0 | Captions & Lyrics editor, waveform timeline, live styling, karaoke and rendered exports |
| v2.4.1 | Improved Nano Banana character-replacement prompt |
| v2.4.0 | Kling reference workflow and reliability/security fixes |
| v2.3 | Higher-quality output formats and trimming improvements |
| v2.2 | Higher-resolution downloads and expanded framing options |
| v2.1 | In-app release checking and updating |
| v2.0 | Windows installer, silent desktop launcher and optional AI Pack |

See [full release notes](RELEASE_NOTES.md) for current releases and [GitHub release history](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases) for earlier downloads.

## Development

Run `python -m unittest discover -s tests -v`, `node tests/test_stream.js` and `node --check static/captions.js`. Build staging with `python build_staging.py`; Inno Setup 6 produces the Windows installer. Cached runtime downloads are checked against pinned SHA-256 values.

See [caption implementation and next steps](CAPTIONS_PLAN.md). This is a focused creator toolkit: a full multitrack editor, integrated stock search, editable motion templates and advanced text animation remain future work.

Media processing runs locally. Downloads, model acquisition, release checks and music recognition use online services. Use media you own or have permission to reuse and check stock-asset licensing before publishing.
