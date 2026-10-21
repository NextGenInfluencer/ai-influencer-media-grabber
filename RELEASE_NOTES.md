# v2.6.1 — Creator Studio stability fixes

- Fixed the social clip grabber failing with `cast is not defined`.
- Added cancellable download/search workers, time limits, failed-download cleanup and active-job tracking.
- Restricted clip links to supported HTTPS platforms and blocked private/reserved network destinations in the Python worker.
- Fixed long-song clip cycling stopping early; repeated clips reuse decoder inputs. Sequences above 600 cuts show a clear limit message.
- YouTube search now respects the requested duration limit.

Validation: 93 Python tests and JavaScript checks passed, including a real repeated portrait/landscape FFmpeg render. External providers may still require authentication or impose restrictions. Reversible effects, clip-audio behavior and stock metadata improvements remain separate work.

Download the Windows Setup EXE below. Close the app before installing over your existing installation. This release does not modify your saved media or caption projects.

# v2.6.0 — CapCut-Style Creator Studio, Multi-Clip Storyboard & Free Video Search

- **CapCut-Style 4-Zone Desktop Studio (`/captions`)**: Redesigned the Captions & Lyrics workspace into a single-screen desktop editor with a Left Icon Dock (`🎬 Media & Clips`, `🌐 Free Videos`, `📝 Lyrics & AI`, `✨ Filters & FX`, `🎵 Audio & Voice`, `🎞️ Canvas & PiP`), Center Video Player Stage, Right Inspector (`⚡ All`, `💬 Lines & Words`, `🎨 Text Style`), and Bottom Multitrack Timeline (`🎬 Clips`, `🎵 Audio`, `💬 Lyrics`) with no blocking modal popups.
- **Multi-Clip Video Sequence Storyboard**: Add up to 30 video or photo clips into a sequence, reorder clips (`←`/`→`), set per-clip durations (`0s` Auto split song evenly or custom seconds like `10s` to cycle clips across the song), preview every clip block on the timeline, and render stitched multi-clip sequences via FFmpeg `concat`.
- **Free Video Search Without API Keys (Mixkit HD Stock & YouTube Shorts / Google) + Social Clip Grabber**:
  - **🔥 Mixkit HD Stock (Free · No Key)**: Built-in zero-key search for 1,370+ free HD watermark-free dance & aesthetic stock videos.
  - **📱 YouTube Shorts / Google (Free · No Key)**: Built-in zero-key vertical video search inside the studio via `yt-dlp`.
  - **🔗 Direct TikTok / Instagram Reel / YouTube Short Clip Grabber**: Paste any TikTok dance video, Instagram Reel, or YouTube Short URL directly in the studio to download without watermark and append to your music video sequence (replacing the clip's audio with your song).
  - **1-Click Dance & Vibe Category Chips**: Instant category buttons (`💃 Dance`, `🔥 Street / Hip-Hop`, `🪩 Club & Party`, `💃 Modern Dance`, `✨ Neon Aesthetic`, `🌆 Night Drive`, `🎤 Concert / DJ`, `🌊 Sunset Vibe`).
- **CapCut-Style Video Filters, Visual FX & Audio FX Suite**:
  - **Video Filters**: `B&W`, `Sepia`, `Vintage Film`, `Cyberpunk Neon`, `Warm Golden Hour`, `Cool Cinema`, `High-Contrast Dramatic`, and `Dreamy Glow` with live browser preview and FFmpeg export.
  - **Visual FX**: Cinematic Vignette, Film Grain, Sharpen, and RGB Chromatic Glitch.
  - **Audio Cleanup & Effects**: FFT Noise Cancellation (`afftdn`), Voice Isolation & Speech Clarity, `Echo`, `Concert Hall Reverb`, `Studio Vocal`, `Lo-Fi Radio`, `Bass Boost`, and `Chorus` in both `/captions` and the Media Tools converter (`/`).
- **Multilingual Karaoke, Audio-Reactive Visualizers, Carousel Studio & Kling Contact Sheets**:
  - 14-language + mixed-language (`en-fr`, `en-ko`, `en-fr-ko`) batch karaoke alignment with Needleman-Wunsch lyric correction, bundled Google Fonts (`Montserrat`, `Roboto`, `Noto Sans KR`, `Oswald`, `Lobster`, `Bangers`), audio-reactive Spectrum & Waveform visualizers, B-roll PiP overlays, intro title cards, Carousel & Still Image Studio, and 6-frame Kling contact sheets.

# v2.5.0 — Captions & Lyrics editor

**Upgrade from v2.4.x using the Windows installer attached to this release.** The older in-app source updater cannot add the new captions component; its startup check will reject the update and preserve your existing app. Close the app before installing. Your media library is retained.

- Open your own or downloaded videos in a dedicated editor with a live preview and waveform timeline.
- Auto-transcribe with the optional AI Pack, paste lyrics, or import SRT/LRC files.
- Correct text and timing, drag caption boundaries, split/merge lines, shift timings, loop playback, and undo edits.
- Style captions with fonts, colors, outlines, backgrounds, positioning, and karaoke word highlighting. Save a reusable style in your browser.
- Autosave projects, reopen them later, render a five-second appearance check, and export a new captioned H.264 video or SRT file without overwriting your original.

Pasted lyrics and estimated word timings are evenly spaced starting points, not automatic alignment to vocals. Review automatic transcription, especially for singing. Browser typography can differ from export; use the rendered check. Separate song audio, automatic alignment of supplied lyrics, and advanced animations remain follow-up features.

Validation includes automated regression checks, real FFmpeg exports, cancellation/restart recovery, and isolated browser editing checks. Transcription tests use fixtures; real song-recognition accuracy is not certified.

# v2.4.1 — Nano Banana character-swap prompts

- Generated prompts now assign the original first frame and influencer reference distinct roles.
- Preserve pose, framing, original clothing, background, and lighting while replacing identity.
- Remove cinematic styling and invented quality keywords; automatic scene captions are explicitly secondary to the images.
- Optional local AI rewriting now preserves the editing constraints.

Compatible with the v2.4.0 in-app updater; restart after applying. Existing prompt text files are unchanged. Prompt output still needs validation with your own images in Nano Banana.

# v2.4.0 — Reference preparation and reliability

Use the Windows installer for the upgrade from v2.3. This release includes Python 3.13.16, Node 26.9.0, and a pinned core dependency set. The old v2.3 source updater cannot migrate its bundled runtime safely.

- Kling Prep creates a matching reference video and first-frame PNG, accepts your Nano Banana edited image, and exports a reusable set. The first frame remains the default.
- Local file access and browser requests are protected; unsafe filenames and remote HTML are escaped. Failed recycle-bin operations preserve files.
- Conversion honors edits and subtitle settings, validates ranges and crops, reports encoder failures, and writes distinct outputs.
- Cleaner preserves originals and orientation; animated files are rejected explicitly rather than flattened. Its descriptions no longer promise to bypass detection.
- Playlist and photo-carousel items share post-processing. History stays deleted, and custom download folders persist in the gallery.
- Stop jobs cancels active external encoders/download helpers and stops subsequent processing. An AI call already running finishes its current step before stopping; Exit remains blocked until work ends.
- AI loading, inference and unloading are serialized. Subtitle translation preserves cue IDs and timing and translates each cue in the selected language.
- Future compatible source updates are staged, checked for unsafe archive paths and dependency changes, syntax-checked and startup-tested before restart. Applying files keeps backups and restores them on interrupted/failed activation. Dependency/runtime migrations use an installer.
- Styling/icons and the downloader JavaScript runtime are bundled. Startup no longer silently upgrades dependencies.

## Validation and practical limits

Automated checks use generated media, an isolated library, deterministic downloader/model fixtures, and real FFmpeg encoders. They cover failure recovery, not only success paths. Real account downloads, live music recognition, large AI model inference, and external Kling/Nano Banana uploads still depend on their services and have not been certified by these tests.

Kling Prep prepares matching files; it does not score pose/identity similarity or contact external AI services. GIF animation is handled by conversion, not metadata cleaning. The gallery uses a cached filesystem listing; a database index and additional content-planning features remain future enhancements. Updates trust this GitHub repository over HTTPS; they are not independently signed releases.
