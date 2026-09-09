# Changelog

All notable changes to the AI Influencer Media Grabber project will be documented in this file.

## [v1.9] - 2026-09-09

### Added
- **Native Desktop Window Mode**: Run the app as an independent, frameless desktop window via `launch-silent.vbs` without opening browser tabs or black CMD windows.
- **In-App Live Console**: Real-time server and download engine logs streamed via Server-Sent Events (SSE) into a built-in terminal widget in the Activity panel.
- **Output Gallery Post Links**: Direct `🔗 Visit Post` action button on all gallery media cards, allowing immediate access to the original post and influencer profile.
- **Automatic Post Link Inference**: Automatically recovers Instagram, TikTok, and YouTube URLs from existing downloaded filenames and history.
- **Companion `.url` Internet Shortcuts**: Every download automatically saves a companion Windows `.url` internet shortcut alongside the media file.
- **Desktop Shortcut Creator**: Script `create_desktop_shortcut.ps1` and `create_shortcut.bat` to place a one-click desktop shortcut with custom icon `assets/app_icon.ico`.
- **Exit App Button**: Clean shutdown action in the navigation header that terminates the Python engine and closes the window.

## [v1.8] - 2026-09-02

### Added
- **Local LLM Engine**: Integrated `llama-cpp-python` with support for Llama 3 8B and Llama 3.2 1B GGUF models.
- **AI Video Summarizer & SEO**: Automatically generates comprehensive video summaries, transcript key points, and SEO hashtags (`_AI_Summary.txt`).
- **Nano Banana Prompt Enhancement**: Uses local LLMs to expand image descriptions into detailed prompt engineering keywords.
- **Decoupled Subtitle Translation**: Subtitle translation runs independently of raw audio transcription checkbox.

### Added
- **AI Prompt Extractor**: Extract Nano Banana 2/Pro & GPT Image 2 optimized prompts directly from images or video frames using local PyTorch vision models (`Salesforce/blip-image-captioning-large`).
- **UI Hard Restart Button**: Added a robust Restart button to the header to automatically reboot the local python server.
- **Auto Subtitle Burner**: Burn subtitles directly into videos using local Whisper AI transcription and FFmpeg.
- **Blurred-Background Padding (9:16)**: Convert horizontal 16:9 videos into vertical 9:16 format with a blurred background canvas.
- **iPhone 15 Pro EXIF Metadata Injector**: Inject realistic iPhone 15 Pro EXIF metadata into cleaned photos and videos in the AI Cleaner tab.
- **Fine-Tuned MB Compression Levels**: Added 50%, 75%, 80%, 85%, and 90% compression tiers with automatic GIF dimension downscaling to comfortably meet Discord 10MB limits.
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
