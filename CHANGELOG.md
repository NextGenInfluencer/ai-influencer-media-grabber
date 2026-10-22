# Changelog

All notable changes to the AI Influencer Media Grabber project will be documented in this file.

## [v2.8.0] - 2026-10-22

### Added & Improved
- **TikTok & Snapchat Signature Aesthetic Filters (1-Click Presets & 0ms Live Preview)**:
  - Added viral social media aesthetic color grading and visual styling presets with instant CSS live stage preview and native FFmpeg export filters:
    - **✨ TikTok Beauty Glow** (`beauty`): Iconic 'Smooth Cam' skin softening, delicate highlight bloom, and luminous porcelain skin tone.
    - **📼 VHS 90s Camcorder** (`vhs`): Authentic vintage home-video look with magnetic chromatic aberration, retro analog tape noise, and scanline depth.
    - **🌅 Teal & Orange Cinematic** (`teal_orange`): High-fashion travel influencer color grade with deep teal shadows and warm sunset skin tones.
    - **💖 Vaporwave Neon** (`vaporwave`): Cyberpunk magenta and electric cyan anime aesthetic with high-saturation pop.
    - **💎 KiraKira / Bling Sparkle** (`bling`): Specular highlight boost and starburst glitz pop.
    - **🐟 Fish-Eye Lens** (`fisheye`): Convex wide-angle bubble lens distortion for skate videos, meme POVs, and dynamic camera angles.
    - **🎞️ Film Noir / Gotham Dark** (`noir`): High-contrast crushed blacks, desaturated silver tones, and moody TikTok noir aesthetic.
- **OpenCV Face Snapping for Stickers & Props (🎯 Snap to Face)**:
  - Added local computer vision face detection using OpenCV (`haarcascade_frontalface_default.xml` & `haarcascade_eye.xml`) with zero cloud dependencies or external API subscriptions.
  - Added **'🎯 Snap to Face (this frame)'** in the Stickers pane: finds the subject's face at the playhead and snaps the sticker to that position (single frame coordinate grab).
  - Three smart snapping targets:
    - 👑 Head / Crown: Positions stickers floating above the head (ideal for crowns, halos, dog/cat ears).
    - 🕶️ Eyes / Shades: Aligns glasses/sunglasses across eye level.
    - 🎭 Face Center: Centers props and masks directly over the facial midpoint.
  - True-color emoji stickers powered by Segoe UI Emoji with proper alpha transparency.
- **Sub-Millisecond Float Precision Sanitization & Auto-Clamping**:
  - Resolved `ValueError: Value must be between ...` caused by floating-point rounding drift when dividing audio ranges during lyric synchronization.
  - `validate_edit` absorbs edge drift (tolerance 0.01s), ensuring lyrics and word timings remain resilient during alignment and auto-estimation while preserving validation integrity.
- **Unified Preview & Export Geometry**:
  - Synchronized sticker coordinate math between the web stage preview and FFmpeg filtergraph using center-anchored bounding boxes.
- **Apple macOS Modern Pro Visual Design**:
  - Upgraded both the Main Dashboard and the Caption Studio to an Apple-inspired Pro design language.
  - Native SF Pro typography stack (`-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display"`), frosted glass acrylic materials (`backdrop-filter: blur(28px) saturate(190%)`), hairline border highlights, and Apple System Blue primary action buttons.
  - Segmented control navigation pills with smooth active indicator physics, refined Apple custom range sliders, and macOS-style sheet dialogs.

## [v2.7.2] - 2026-10-21

### Added & Improved
- **Cut-to-the-Beat / Auto Beat-Drop Snapping (`⚡ Cut to Beat`)**:
  - Added 1-click `⚡ Cut to Beat` button in the sequence storyboard bar.
  - Automatically analyzes the song's audio peaks and beat transients (`CaptionTiming.detectBeats`), snapping all clip cut points to the nearest musical beat drops for effortless rhythmic TikTok/Reels-style music video editing.
- **Per-Clip Speed Ramping & Slow-Mo (0.25× to 4×)**:
  - Added dedicated speed multiplier dropdown (`0.25× Slow`, `0.5× Slow`, `0.75×`, `1× Normal`, `1.25×`, `1.5×`, `2× Fast`, `4× Hyper`) on every clip pill in the sequence storyboard.
  - Configures per-segment video presentation timestamps (`setpts=PTS/{speed}`) and audio speed filters (`atempo={speed}`), maintaining bit-exact audio synchronization and slow-mo video fluidity.
- **Stickers, Emojis & Transparent Graphic Overlay Track**:
  - Added a dedicated **Stickers** dock tab and pane (`data-dock-pane="stickers"`).
  - 1-click viral reaction emojis (`🔥`, `💃`, `👑`, `✨`, `💯`, `💖`, `⚡`, `🎧`, `🚀`, `🪩`, `⭐`, `🎉`) rendered as high-res transparent PNG stickers with automatic Pillow typography.
  - Direct upload support for custom transparent PNG, animated GIF, and WebP graphics.
  - Precise timing & placement controls: start time, duration, X/Y screen position, size scale, opacity, fade in/out, and motion entrance animations (`pop` bounce, `fade`, `slide`).
  - Real-time video player stage preview via `#stageSticker` and multitrack timeline visualization on `#videoTrackLane`.

## [v2.7.1] - 2026-10-21

### Added & Improved
- **Split Clip at Playhead (`Ctrl+B` / Split Clip Button)**:
  - Added 1-click `✂️ Split Clip` button in the center playback controls, `✂️ Split at Playhead` in the storyboard sequence bar, and universal `Ctrl+B` / `Cmd+B` keyboard shortcut.
  - Automatically splits the active video or photo clip in the sequence at the current playhead position (`video.currentTime`) into two adjacent segments with exact millisecond precision.
  - Automatically freezes relative auto-split durations so surrounding clip timings and lyrics alignment remain 100% stable.
- **Custom Font Upload / User Font Import (`.ttf` / `.otf`)**:
  - Direct font drag-and-drop / file upload (`POST /api/captions/fonts/upload`) supporting any TrueType or OpenType font up to 25MB.
  - Strict security validation: verified TrueType/OpenType magic headers (`\x00\x01\x00\x00`, `OTTO`, `true`, `typ1`, `ttcf`), Pillow parsing, and font table metadata extraction.
  - Instant live typography: dynamically injects `@font-face` rules for 0ms web canvas preview without page reloads.
  - Bit-exact ASS/libass export: custom fonts are automatically copied to temporary `caption_fonts/` during rendering so FFmpeg renders custom typography without requiring OS-level administrator font installation.
- **Advanced Export Quality & Framerate Presets**:
  - Added **Smooth 1080p 60fps** (`60fps`: CRF 17, 320k audio, 60fps framerate) for ultra-fluid dance and social media reels.
  - Added **4K Ultra HD 2160p** (`4k`: CRF 15 studio master, 320k audio, 2160p scaling) for vertical 2160×3840 and horizontal 3840×2160 exports.
  - Integrated into the finish bar (`#renderQuality`) and validated in backend pipeline.
- **Timeline Audio Indicators**:
  - Visual audio badge (`🔊` / `🔇`) rendered directly on sequence clip blocks in the bottom timeline (`#videoTrackLane`).
  - Displays instant visual feedback whether each clip has active audio or is muted/silent.

## [v2.7.0] - 2026-10-21

### Added & Improved
- **CapCut-Style Video Transitions Between Multi-Clip Cuts**:
  - Seamlessly transition between cuts in multi-clip video sequences with 9 transitions: `Dissolve / Crossfade` (`fade`), `Fade to Black` (`fadeblack`), `Flash White` (`fadewhite`), `Slide Left` (`slideleft`), `Slide Right` (`slideright`), `Zoom / Circle Crop` (`circlecrop`), `Wipe Left` (`wipeleft`), `Wipe Right` (`wiperight`).
  - Configurable transition durations from 0.1s to 2.0s with frame-accurate FFmpeg `xfade` chaining and color-dip blending.
- **100% Non-Destructive Reversible Video Filters & Visual FX**:
  - Composition generation and editing now preserves raw pristine pixels (`bake_fx=False`).
  - Switching filters (e.g. `Vintage`, `Cyberpunk`, `Warm`, `Noir`) or returning to `None` immediately restores untouched original colors without double-baking or pixel degradation.
  - GPU-accelerated 0ms CSS preview in the browser and dynamic single-pass FFmpeg application during export.
- **Multi-Clip Background Audio Mixing with Silence Fallback**:
  - Background audio tracks from video clips in multi-clip sequences are mixed under the main song with adjustable volume and audio ducking.
  - Generates synchronized stereo silence (`anullsrc=r=44100:cl=stereo`) for still photos or muted clips so mixed sequences never desynchronize.
- **Animated Caption & Title Card Motion Presets**:
  - Added `Zoom In` (smooth scale-in entrance) and `Typewriter` (progressive character-by-character typewriter reveal) animations.
  - Implemented both in the interactive player stage (`drawCaption`) and in exported ASS subtitles.

## [v2.6.1] - 2026-10-21

- Fixed the social clip grabber's missing `cast` failure. Downloads now run in a cancellable worker with a three-minute deadline, file-size/duration limits, live-stream filtering, isolated temporary files and active-job tracking.
- Restricted clip URLs to HTTPS YouTube, TikTok and Instagram hosts without credentials or custom ports; disabled unrelated/generic extractors for this workflow.
- The isolated Python download worker rejects private/reserved socket destinations, including redirected and DNS-resolved targets.
- Added a cancellable, time-limited YouTube search worker and respected the requested duration limit.
- Fixed long-song cycling silently stopping after 20 repeats/60 cuts. Repeated clips share decoder inputs; sequences above 600 cuts now show an explicit error.
- Added route-level download/cancellation tests and a real FFmpeg repeated portrait/landscape regression check.
- Remaining audit items (reversible effects, clip audio and stock metadata) are not included in this stability release.

## [v2.6.0] - 2026-10-21

### Added & Improved
- **CapCut-Style 4-Zone Desktop Studio (`/captions`)**:
  - Redesigned the Captions & Lyrics editor into a full-viewport 4-zone workspace with a Left Icon Dock (`🎬 Media & Clips`, `🌐 Free Videos`, `📝 Lyrics & AI`, `✨ Filters & FX`, `🎵 Audio & Voice`, `🎞️ Canvas & PiP`), Center Video Player Stage, Right Inspector (`⚡ All`, `💬 Lines & Words`, `🎨 Text Style`), and Bottom Multitrack Timeline (`🎬 Clips`, `🎵 Audio`, `💬 Lyrics`) with zero blocking modal popups.
- **Multi-Clip Video Sequence Storyboard**:
  - Stitch up to **30 video or photo clips** into a sequence (`settings.sequence`), reorder clips (`←`/`→`), set per-clip durations (`0s` Auto split song evenly or custom seconds like `10s` to cycle clips across the song), preview every clip block on `#videoTrackLane`, and render stitched multi-clip sequences via FFmpeg `concat`.
- **Free Video Search Without API Keys (Mixkit HD Stock & YouTube Shorts / Google) + Social Clip Grabber**:
  - **🔥 Mixkit HD Stock (`mixkit`)**: Built-in zero-key search for 1,370+ free HD watermark-free dance & aesthetic stock videos.
  - **📱 YouTube Shorts / Google (`youtube`)**: Built-in zero-key vertical video search via `yt-dlp`.
  - **🔗 Direct TikTok / Instagram Reel / YouTube Short Clip Grabber (`POST /api/captions/stock/grab-url`)**: Paste any TikTok dance video, Instagram Reel, or YouTube Short URL directly inside the studio to download without watermark and append to your music video sequence (replacing the clip's audio with your song).
  - **1-Click Dance & Vibe Category Chips**: Instant category buttons (`💃 Dance`, `🔥 Street / Hip-Hop`, `🪩 Club & Party`, `💃 Modern Dance`, `✨ Neon Aesthetic`, `🌆 Night Drive`, `🎤 Concert / DJ`, `🌊 Sunset Vibe`).
- **CapCut-Style Video Filters, Visual FX & Audio FX Suite**:
  - **Video Filters**: `B&W`, `Sepia`, `Vintage Film`, `Cyberpunk Neon`, `Warm Golden Hour`, `Cool Cinema`, `High-Contrast Dramatic`, and `Dreamy Glow` with live browser preview and FFmpeg export.
  - **Visual FX**: Cinematic Vignette, Film Grain, Sharpen, and RGB Chromatic Glitch.
  - **Audio Cleanup & Effects**: FFT Noise Cancellation (`afftdn`), Voice Isolation & Speech Clarity, `Echo`, `Concert Hall Reverb`, `Studio Vocal`, `Lo-Fi Radio`, `Bass Boost`, and `Chorus` in both `/captions` and the Media Tools converter (`/`).
- **Multilingual Karaoke, Audio-Reactive Visualizers, Carousel Studio & Kling Contact Sheets**:
  - 14-language + mixed-language (`en-fr`, `en-ko`, `en-fr-ko`) batch karaoke alignment with Needleman-Wunsch lyric correction, bundled Google Fonts (`Montserrat`, `Roboto`, `Noto Sans KR`, `Oswald`, `Lobster`, `Bangers`), audio-reactive Spectrum & Waveform visualizers, B-roll PiP overlays, intro title cards, Carousel & Still Image Studio, and 6-frame Kling contact sheets.

## [v2.4.0]

## [v2.3] - 2026-10-01

### Added & Improved
- **100% Automatic Lossless Stream-Copy (`-c copy`)**: Trimming a video without changing aspect ratio or burning subtitles now automatically executes a bit-exact stream copy in ~0.1s with 0.000% generational quality loss.
- **Pro Master Formats**: Added dedicated high-fidelity export formats to Media Tools:
  - **`MP4 (4K / H.265 Master)`**: Modern HEVC compression with Apple and Windows compatible `hvc1` tags, preserving micro-details on 4K footage.
  - **`MOV (Apple ProRes 422 Studio Master)`**: 10-bit intra-frame master quality (HQ) for professional editing in Premiere Pro, DaVinci Resolve, and Final Cut.
  - **`MKV (Matroska Master)`**: Universal lossless container preserving full-fidelity audio and video streams.
  - **`WAV (Lossless PCM Audio)`**: Uncompressed 16-bit audio output.
- **Master Quality Profiles**: Added clear, intuitive quality presets in the converter:
  - **💎 Maximum Quality (Visually Lossless — 100% Detail)**: CRF 14 default, ensuring AI facial generation details, skin textures, and 4K resolution remain crisp without compression artifacts.
  - **👑 Pure Lossless (CRF 0 — Bit-Exact Copy)**: True mathematical lossless encoding pass.
  - **Standard Web (Balanced Quality)**: Standard web-optimized compression (CRF 22).
- **Interactive Click-to-Track Seamless Playback & Non-blocking Controls**:
  - Interactive face tracking overlay positioned with bottom clearance (`bottom-12`), leaving native HTML5 video controls (scrubber bar, play/pause, timecode, volume) 100% unobstructed.
  - Auto-synchronization with HTML5 video `play`, `pause`, and `seeked` events: pauses automatically to inspect clear frames, or allows clicking faces directly while playing.
  - Reticle marker decoupled from overlay layer so locked target pin remains visible during subsequent playback.
- **Auto-Shutdown Watchdog & Port Management**:
  - Client heartbeat beacon shuts down the background Python engine when the window is closed, freeing port `5000` and releasing system RAM cleanly.
- **Gallery Likes & Quick-Access Favorites**: Added 1-click heart favoriting on all gallery media cards and in the fullscreen preview modal. Includes persistent on-disk storage (`favorites.json`), a live header counter badge (`Liked (X)`), pinned heart badges on favorited cards, and 1-click quick-filtering to access liked media instantly.
- **High-Bitrate Audio Default**: AAC and MP3 encoding upgraded to 320 kbps studio bitrate.

## [v2.2] - 2026-09-30

### Added & Improved
- **YouTube Max Quality (4K Ultra HD & 2K) Support**: Added a prominent **Quality / Resolution** selector pre-selected to **🔥 Max Quality (4K / 2K / Best)** by default, with choices for 4K (2160p), 2K (1440p), 1080p, 720p, 480p, and MP3 audio.
- **Node.js JavaScript Challenge Solver**: Integrated automated Node.js challenge solving (`js_runtimes` & `remote_components: ejs:github`) into `yt-dlp` to bypass YouTube signature deciphering restrictions, unlocking pristine 4K streams without fallback throttling.
- **Universal Audio Pairing**: Video streams now pair automatically with `bestaudio[ext=m4a]` (AAC), ensuring native playback on Windows Media Player, QuickTime, and Premiere Pro without extra codecs.
- **Persistent User Preferences**: Quality choices and codec options are now automatically remembered across sessions in `localStorage`.
- **Live Trim Duration Badge & Validation**: Video Trimmer displays a live cut-duration badge with real-time feedback and validation to prevent invalid end timestamps.
- **Media Preview Lightbox Modal**: Clicking any card in the Output Gallery opens a responsive lightbox modal with embedded video, audio, and image playback, quick action buttons, and keyboard navigation (`Escape`, `ArrowLeft`, `ArrowRight`).
- **Download History Auto-Reconciliation**: Automatically scans and backfills missing files into `history.json` on startup, with downloads strictly ordered newest-first.
- **Non-blocking Windows Explorer Integration**: Folder buttons across the gallery, history, and converter now use non-blocking explorer selection with directory fallback.
- **Multi-Person Face Tracking Target Selection**: Media Tools converter now supports smart focus selection when multiple subjects are in frame:
  - 👑 **Dominant Subject**: Automatically tracks and centers the primary speaker based on face size with proximity hysteresis.
  - 🎯 **Interactive Click-to-Track**: Preview your video and click directly on any speaker's face to place a glowing purple target reticle; locks tracking onto that exact person regardless of who else speaks or moves in the scene.
  - 👈 **Left Person (Speaker 1)**: Locks onto and follows the person on the left side of the frame with left-half boundary clamping.
  - 👉 **Right Person (Speaker 2)**: Locks onto and follows the person on the right side of the frame with right-half boundary clamping.
  - 👥 **Center Framing**: Frames both speakers together, smoothly panning to keep both subjects visible in 9:16.
- **🎙️ Podcast Split-Screen Mode (Stacked 9:16)**: Added Opus Clip & CapCut style stacked layout for two-person interviews and podcasts. Simultaneously crops Speaker 1 on the top half and Speaker 2 on the bottom half with a crisp divider line, formatted directly into vertical 9:16 with zero audio re-encoding loss.
- **Temporal Centroid Tracking & Stability Fix**: Fixed sudden camera jitter and erratic switching between subjects by adding spatial-temporal continuity to the face tracker. If a subject tilts their head or looks away, the crop smoothly holds position instead of jumping across the room to other people.
- **Clean Desktop Lifecycle & Auto-Shutdown Watchdog**: Closing the app window now cleanly terminates the background Python engine after a grace period, releasing port `5000` and immediately freeing ~700 MB of system RAM. Ongoing downloads or conversions are guarded to complete safely before shutdown.
- **Smart Launcher Hot-Reload Detection**: `launch-silent.vbs` and `/api/health_check` compare on-disk file modification times with server uptime. If code files were updated, the launcher automatically reboots the server to load the latest code seamlessly.

### Fixed
- **Frame-Accurate Clip Trimming Bug**: Fixed FFmpeg duration calculation when trimming clips (`-ss <start> -t <duration>`). Setting timestamps like `00:00:14` to `00:00:28` now produces an exact 14.0-second clip instead of taking 28 seconds.
- **4K Face Tracking Divisibility by 2 Error**: Fixed `libx264` encoder failure (`width not divisible by 2 (1215x2160)`) on 4K 9:16 vertical face crops by enforcing even pixel dimensions (`1214x2160`) and adding an automatic even-dimension scaling filter.
- **Unicode UTF-8 Logging Error**: Fixed `UnicodeEncodeError` in converter debug logging when handling filenames containing special characters or fullwidth symbols (e.g. `｜`).
- **Desktop Launcher Offline Detection Bug**: Fixed COM exception handling in `launch-silent.vbs` where an offline server check was falsely detected as online due to non-short-circuiting logic, ensuring the Python backend boots reliably on launch.
- **Download History Indentation Bug**: Fixed download completion handler in `app_local.py` so downloads without frame extraction are immediately indexed into history.

## [v2.1] - 2026-09-13

### Added
- **1-Click In-App GitHub Auto-Updater (OTA)**: Users can now update the application seamlessly from the latest GitHub releases without having to re-download or reinstall the `.exe` installer or ZIP package.
- **Top Navigation Version Badge**: Displays current installed version with on-demand update checks, dynamically converting to an animated "Update Available" badge when a new release is detected.
- **Glassmorphism Update Modal**: Displays release title, release notes, published date, direct GitHub release link, real-time download/extraction progress bar, and live hot-patch status logs.
- **Safe Hot-Patch Architecture**: Safely hot-patches application code, templates, and assets while protecting user downloads (`Documents/Media Grabber`), user settings, Python runtimes (`.venv`, `python_runtime`), and version control directories.
- **Automatic Dependency Sync**: Automatically detects changes in `requirements.txt` upon updating and updates Python packages in the runtime environment.

### Fixed & Improved
- **Robust Server Restart**: Guaranteed process exit and scheduled re-launch helper preventing port collision and hanging states during restarts.
- **Code Audit & Type Safety**: Cleaned redundant `str()` conversions, eliminated uninitialized variable references, and ensured 100% test pass rate across all API endpoints.

## [v2.0] - 2026-09-09

### Added
- **1-Click Windows Setup Installer (`.exe`)**: Standalone installer powered by Inno Setup bundling an embedded portable Python 3.10 runtime. Installs in seconds without requiring Python or administrator privileges (`AI-Influencer-Media-Grabber-v2.0-Setup.exe`).
- **Modular Dependency Architecture**: Separated lightweight Core downloader dependencies (`requirements.txt`, ~80MB, fast 15-second setup) from the heavy AI Engine stack (`requirements-ai.txt`, PyTorch, Whisper, Vision BLIP, LLaMA).
- **In-App 1-Click AI Pack Installer**: Added visual AI Engine status badge in the header, an interactive AI Pack installer modal with real-time download progress and log stream, and smart auto-detection whenever an AI feature is invoked.
- **Standalone `install_ai.bat` Script**: Convenient 1-click batch script for manual or offline AI Engine pack installation.
- **Graceful Fallback & Lazy Imports**: Dynamic lazy imports in `ai_prompter.py` and `app_local.py` ensuring the application boots immediately and runs all video downloading and conversion tools with 100% reliability even when PyTorch is not yet installed.
- **Native Desktop Window Mode**: Run the app as an independent, frameless desktop window via `launch-silent.vbs` without opening browser tabs or black CMD windows.
- **In-App Live Console**: Real-time server and download engine logs streamed via Server-Sent Events (SSE) into a built-in terminal widget in the Activity panel with syntax highlighting, timestamps, and auto-scroll.
- **Output Gallery Post Links**: Direct `🔗 Visit Post` action button on all gallery media cards, allowing immediate access to the original post and influencer profile.
- **Automatic Post Link Inference**: Automatically recovers Instagram, TikTok, and YouTube URLs from existing downloaded filenames and history.
- **Companion `.url` Internet Shortcuts**: Every download automatically saves a companion Windows `.url` internet shortcut alongside the media file.
- **Desktop Shortcut Creator**: `create_shortcut.bat` and `create_desktop_shortcut.ps1` to place a one-click desktop shortcut with custom icon `assets/app_icon.ico`.
- **Exit App Button**: Clean shutdown action in the navigation header that cleanly terminates the Python engine and closes the window.
- **Retina Interface Previews**: Fresh high-resolution 2x screenshots for all 4 application tabs in `assets/`.

### Security & Privacy
- Sanitized configuration files (`pyrightconfig.json`) and added comprehensive `.gitignore` rules to ensure zero developer paths or user media data are present in distributions.
- Heavily blurred card image thumbnails in preview documentation for complete privacy.

## [v1.8] - 2026-09-02

### Added
- **Local LLM Engine**: Integrated `llama-cpp-python` with support for Llama 3 8B and Llama 3.2 1B GGUF models.
- **AI Video Summarizer & SEO**: Automatically generates comprehensive video summaries, transcript key points, and SEO hashtags (`_AI_Summary.txt`).
- **Nano Banana Prompt Enhancement**: Uses local LLMs to expand image descriptions into detailed prompt engineering keywords.
- **Decoupled Subtitle Translation**: Subtitle translation runs independently of raw audio transcription checkbox.
- **Dynamic Face-Tracking Auto-Crop (Converter)**: Converter can track the speaker's face frame-by-frame and keep them centered in vertical 9:16 format.
- **SRT Subtitle Export**: Direct `.srt` subtitle file export alongside downloaded or converted videos.

## [v1.7] - 2026-08-28

### Security & Stability
- Fixed path traversal vulnerabilities and plugged memory leaks in download tasks.
- Plugged SSE loop hangs and temporary folder creation leaks.
- Automatic RAM and VRAM garbage collection; AI models (Whisper and BLIP) now unload after 10 minutes of inactivity.
- Native keyboard shortcuts (`Ctrl/Cmd + Enter` to start tasks, `Escape` to close modals).
- Persistent `localStorage` settings across sessions.
- Auto-refreshing gallery and 2-second gallery cache to prevent filesystem thrashing.

## [v1.6] - 2026-08-20

### Added
- **AI Prompt Extractor**: Extract Nano Banana 2/Pro & GPT Image 2 optimized prompts directly from images or video frames using local PyTorch vision models (`Salesforce/blip-image-captioning-large`).
- **UI Hard Restart Button**: Added a robust Restart button to the header to reboot the local Python server with one click.
- **Auto Subtitle Burner**: Burn subtitles directly into videos using local Whisper AI transcription and FFmpeg.
- **Blurred-Background Padding (9:16)**: Convert horizontal 16:9 videos into vertical 9:16 format with a blurred background canvas.
- **iPhone 15 Pro EXIF Metadata Injector**: Inject realistic iPhone 15 Pro EXIF metadata into cleaned photos and videos in the AI Cleaner tab.
- **Fine-Tuned MB Compression Levels**: Added 50%, 75%, 80%, 85%, and 90% compression tiers with automatic GIF dimension downscaling to meet Discord 10MB limits.
- **Cross-Platform Compatibility**: macOS and Linux shell launcher `run.sh` and platform-native file manager opening support (`open`, `xdg-open`).

### Fixed
- **Converter Engine**: Fixed a critical bug where Flask request contexts were dropping in background threads causing silent converter crashes.
- **Media Tools UI**: Fixed missing HTML attributes preventing Trim Start and Trim End times from being sent to the backend.

## [v1.5]

### Added
- Built-in HTML/JS folder and file browser modal replacing OS native dialogs.
- Recursive gallery scanning for subdirectories.

### Optimized & Fixed
- Daily `yt-dlp` update checks for faster application startup.
- Increased Waitress server worker threads to 8.
- Fixed asyncio event loop leaks and exception handling.

## [v1.4]

### Added
- Dedicated **AI Cleaner** tab for batch metadata stripping & SynthID pixel scatter.
- Auto-Bypass option in Downloader tab.
- Self-contained FFmpeg binaries via `imageio_ffmpeg`.
- Live SSE Terminal for batch cleaner status streaming.

## [v1.3]

### Added
- Media Tools Converter for offline editing, cropping, and local audio transcriptions using Whisper AI.
