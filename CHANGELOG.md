# Changelog

All notable changes to the AI Influencer Media Grabber project will be documented in this file.

## [v1.6] - 2026-07-24

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
