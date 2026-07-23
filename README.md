# 🎥 AI Influencer Media Grabber

![Version 1.4](https://img.shields.io/badge/Version-1.4-blue?style=for-the-badge) ![UI Preview](https://img.shields.io/badge/UI-Airi_Studio-f472b6?style=for-the-badge)

## 🌟 What is the AI Influencer Media Grabber?

**AI Influencer Media Grabber** is your ultimate, all-in-one desktop toolkit for social media content creators, video editors, and AI artists. Instead of relying on sketchy, ad-filled websites to download videos or convert files, this app runs **100% locally on your computer** with a beautiful, modern interface.

Whether you're building a massive reference folder of TikTok trends, extracting music from Instagram Reels, pulling perfectly-framed thumbnails for YouTube shorts, or prepping videos for AI generation tools like Kling—this grabber automates the entire workflow in just a few clicks. It's safe, blazing fast, completely private, and incredibly powerful.

## ✨ Features

### 📥 Ultimate Download Engine
- **Platform Support:** Flawlessly downloads videos from TikTok, YouTube, Twitter, and more.
- **Instagram Master:** Easily rip entire Instagram profiles, Reels, and multi-photo Carousels.
- **Dual-Engine Auto-Fallback:** Uses `yt-dlp` for heavy lifting, and instantly falls back to `gallery-dl` to capture tricky photo carousels.
- **Metadata Extraction:** Automatically pulls post captions, titles, and descriptions and saves them as text files alongside your media.
- **Smart Queue System:** Paste multiple links at once. The app processes them all sequentially in the background.

### 🤖 AI Processing & Tweaks
- **Auto-Transcription:** Uses local AI (Whisper) to automatically generate text transcripts from downloaded videos.
- **Song Identification:** Runs Shazam on downloaded videos to automatically identify background music.
- **First Frame Extraction:** Automatically extracts the perfectly-framed first thumbnail of a video as an image.
- **Kling / AI Tool Compatibility:** Optionally forces strict `H.264` / `mp4` standard encoding on all downloads so they never crash or artifact in AI video generators like Kling.
- **Auto-Bypass AI Detection (New!):** Automatically apply a 0.5% edge crop and inject microscopic film grain into downloaded videos and photos to safely destroy invisible SynthID watermarks and strip all `C2PA` metadata, bypassing social media AI filters!

### 🧹 AI Cleaner Batch Processor (New!)
A dedicated tab to batch-process your existing media folders to strip them of AI watermarks!
- **Target Folders:** Select an entire folder (or single file) and clean all AI metadata in one click.
- **Live Terminal:** Watch the Python processing engine rip through your files in a cool hacker-style terminal right in the browser.
- **Smart Safety:** Every file processed is automatically copied, 100% untouched, into a `backup_unscrambled` folder just in case you ever need the pure original. Files are also logged so they're never double-processed.

### 🛠️ Media Tools Converter
A dedicated second tab in the app featuring a full offline media editing suite:
- **Convert:** Instantly convert videos to GIF, MP3, MP4, or PNG frames.
- **Edit:** Crop dimensions, resize resolutions, and trim video lengths without opening Premiere.

---

## ?? How to Download & Run (For Beginners)

If you don't know how to use the command line, don't worry! Running this app is incredibly simple.

### 🛠️ Step 1: Install Python (Prerequisite)
If you already have Python installed, you can skip this step!

1. **Download Python (Version 3.10 or newer)** from the official website:
   👉 [Click here to download Python](https://www.python.org/downloads/)
2. Open the downloaded installer.
3. ⚠️ **CRITICAL STEP**: When the installer opens, look at the **very bottom of the first window**. You **MUST** check the small box that says **"Add python.exe to PATH"** before clicking Install. If you don't check this box, the app will not work!
4. Click "Install Now" and let it finish.

### 🚀 Step 2: Download & Run Airi Studio
1. Go to the top of this GitHub page and click the green **"<> Code"** button.
2. Click **"Download ZIP"**.
3. Once downloaded, **Extract/Unzip** the folder anywhere on your computer (like your Desktop).
4. Open the extracted folder and simply **double-click** the file named `run.bat`.
5. *(Optional)* **Double-click** the file named `create_shortcut.bat`! This will place a convenient app icon right on your Desktop so you never have to open this folder again.

### That's it! 🎉
The `run.bat` script is fully automated. It will download everything it needs, install all the requirements, and instantly pop open the beautiful Airi Studio interface in your web browser. 

*Note: By default, all of your downloaded videos, photos, and converted media will be neatly saved in your `Documents/Media Grabber` folder!*

*Note: The very first time you run it, it might take a few minutes to download the AI models and setup the environment. Every time after that, it will launch instantly!*

---

## 📜 Changelog

### v1.4 (Current)
- **New Feature:** `AI Cleaner` Tab added to the main UI. You can now browse for a folder or file to securely scramble pixels and strip metadata in batch!
- **New Feature:** Auto-Bypass added to the Studio Downloader tab. Instantly bypass AI detectors when downloading media from the web.
- **Enhancement:** All FFmpeg binaries are fully self-contained using `imageio_ffmpeg` (no more manual installations!).
- **Safety:** Automatic backup folder generation (`backup_unscrambled`) and duplicate-prevention tracking added.
- **UI:** Added Live Terminal for the Batch Cleaner utilizing Server-Sent Events (SSE).

### v1.3 
- Added Media Tools Converter for offline editing, UI refinements, and local audio transcriptions using Whisper AI.
