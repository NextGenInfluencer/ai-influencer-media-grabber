# Free Creator Studio — implementation and resume plan

Saved 21 October 2026. Phases 1 through 6 implemented and verified in the source checkout. No scheduled run has been created.

## Product goal

Evolve this Windows app into a free, local creator studio for reference downloads, personal video/photo editing, music videos, lyrics, Reels, TikTok and YouTube Shorts. Aim for the useful everyday workflow of a free CapCut-style editor and Videobolt-style music templates, delivered in tested phases. A complete CapCut replacement is a substantial ongoing project, not a single upgrade. Do not copy proprietary templates or promise every feature at once.

Keep the working downloader and media tools. Existing priorities include Instagram photos/carousels/Reels, TikTok source downloads without the extra platform download watermark where available, YouTube/Shorts best available quality, MP3 extraction, GIFs, crop/trim/resize, and first-frame Nano Banana → Kling preparation. H.264 compatibility conversion stays optional. Preserve the comprehensive README, screenshots and release history.

References supplied by the user: https://lyricpotato.com/ (waveform and lyric timing), https://videobolt.net/ (music videos, backgrounds, templates and visualizers), https://www.youtube.com/watch?v=Dp85NmrfuAI (lyric-video tutorial). The tutorial contents were not accessible in the earlier web read; inspect it before attributing specific features to it.

## Baseline before Phase 1 (historical)

- Published v2.5.0 installer: caption editor, imports, automatic transcription, live style preview, timeline and exports.
- Newer local/GitHub source: stable-ts supplied-text alignment, audio-only song creation with colour/photo/looped-video background, baked waveform visualizer, three bundled Google Fonts, restored README.
- Latest fix: caption timing validation is bundled in captions.js; tests exercise the Estimate button and moving word highlight. Invalid backwards timings are rejected.
- SRT import provides line timings only. Estimate word timings still applies to one selected line. Full-text alignment recalculates line boundaries. Neither is the requested preserve-SRT batch karaoke operation.
- Background and waveform currently become part of a generated base video. Changing them requires creating another version. Stock sites are links, not integrated search/import. Existing fonts are a small selection.
- Real alignment was exercised on generated speech, not validated on the user's mixed Greek/English Suno song. Do not describe song quality as proven.

## Phase 1 — automatic karaoke for existing subtitles (first implementation)

User workflow: import SRT → Add karaoke timing → review flagged lines → export. No need to retranscribe or click every line.

1. Add an explicit whole-project action and a selected-line retry action. Preserve caption text, order, line breaks, start/end times and existing styles exactly.
2. Use stable-ts constrained alignment (evaluate align_words against the installed version) to locate words inside each existing cue interval. Batch bounded groups where practical; reuse the shared Whisper model and AI lock. Avoid loading a model for each line.
3. Support English/Greek and mixed-language projects. Infer a suggested language from text/script with a per-line override; evaluate bilingual lines rather than assuming script detection solves language selection. Keep the existing transcription language control separate from alignment controls.
4. Show progress, cancellation and counts: aligned, needs review, missing timings. Use measurable failure/quality heuristics such as zero-duration words or compressed timing; do not invent calibrated confidence scores.
5. Keep failed lines unchanged and visibly flagged. Never silently label uniform estimates as audio alignment. Offer explicit approximate timing for remaining lines if the user chooses it.
6. Snapshot/backup before applying results, support undo, preserve saved captions on cancellation/failure, and prevent stale jobs from overwriting edits. Make whole-project changes transactional or stage partial results for explicit application.
7. Add jump-to-next-review, loop-current-line and editable word boundaries. Explain in the preview when highlighting has no timings. Make current playback line and selected editing line visually distinct.
8. Improve karaoke choices: current-word highlight first; then cumulative highlight and word pop only after consistent preview/export behavior exists.

Acceptance: imported line timestamps and text remain unchanged; highlighting advances across the whole song; repeats, instrumental gaps, Greek/English text and missing words are handled; failures are reviewable; cancellation/undo/reload work; actual browser clicks and rendered output are tested. Use a user-authorized copy of their song/SRT for real-song evaluation, without changing their working project.

## Phase 2 — editable song and background composition

Start from an audio file without needing a video. Upgrade the current creation dialog into a persistent project.

- Keep original media as assets; store composition settings instead of baking backgrounds into the only editable source.
- Replace a background without losing lyrics, timings or styles. Use uploaded images/videos, downloaded media or library assets.
- Portrait 9:16, landscape 16:9 and square formats; fit/fill, crop position, blur, dimming, colour overlays and optional slow pan/zoom.
- Song trim/offset, volume, fade-in/out and mute/replace background audio. Video looping and image duration controls.
- Background changes, lyrics and audio remain synchronized while seeking, looping and changing playback speed.
- Reusable project save/open, duplicate, autosave recovery and relink missing media.

Architecture gate: introduce a versioned project schema with assets, tracks, clips, source offsets, transforms and text styles. Migrate existing caption projects non-destructively. Keep old projects readable and retain rollback copies. Establish a shared timeline/timebase and render specification before expanding features.

## Phase 3 — templates, fonts and audio-reactive visuals

- Curated locally bundled Google Fonts with license files and tested Greek coverage; searchable family picker, favourites and reusable style presets. Evaluate user-installed/local font import later with validated formats.
- Lyric presets: clean captions, outlined bold, boxed captions, karaoke, word pop and simple fade/slide. Controls for line length, spacing, safe placement and highlight colour.
- Editable audio visualizers: waveform and spectrum bars first, then circular layouts if practical. Colour, size, position, sensitivity and smoothing controls.
- Prepare reusable audio-analysis data once. Define identical timing/math for live visuals and final export; do not deliver effects that only work in the browser.
- Reusable music-video templates combining background, font, text position and visualizer. Include plain designs that work with the user's own artwork.

Acceptance: effects follow audio through scrubbing and offsets, remain in sync on export, and perform acceptably on ordinary hardware. Verify font/glyph coverage and line wrapping, not merely successful encoding.

## Phase 4 — integrated stock background browser

- Evaluate Pexels and Pixabay APIs against their current official documentation: keys, quotas, attribution, caching, permitted download use and license restrictions. Do not assume unlimited free API access or require a paid service for core editing.
- Search inside the app, filter orientation/duration, preview, select an appropriate resolution, download with progress/cancellation and add to the project.
- Retain source page, creator and licensing/provenance information with each asset. Display applicable requirements clearly.
- Validate provider URLs and redirects, restrict remote destinations, bound file size/type, and handle offline/rate-limit failures.
- Keep upload and local-library backgrounds working without API keys. Do not scrape around a provider's API restrictions.

## Phase 5 — practical multitrack short-video editor

Build on the Phase 2 project schema, not a second disconnected editor.

1. Video/image track, audio track and caption/text track; drag, split, trim, reorder, snap and zoom.
2. Preview transforms, crop/reframe and safe-area presets; reuse existing conversion/export tools.
3. B-roll/image overlays, title cards, simple transitions and speed adjustments.
4. Volume mixing, fades and optional ducking. Re-evaluate caption timing when speed or source offsets change.
5. Basic colour/exposure controls and simple keyframes for position, scale and opacity.
6. Proxy previews and cancellable render queue; progress, useful errors and output-quality presets.

Defer complex compositing, extensive effects marketplaces, collaborative cloud editing and full desktop-editor parity until the core workflow is stable.

## Phase 6 — photo, carousel and reference workflow polish

- Image crop/resize/rotate, consistent canvas presets and text overlays for still images.
- Carousel workspace: reorder slides, apply shared styling, safe margins and export ordered files; retain downloaded carousel ordering.
- Contact sheets/frame selection alongside the first-frame default for Kling. Keep the user's preferred first-frame workflow easy.
- Review download quality choices, original preservation and audio-only UX using representative supported media. Avoid changing the tested downloader unnecessarily.
- Optional future vocal separation and larger transcription models: evaluate dependency size, hardware cost, licensing and real benefit before bundling.

## Cross-cutting quality and release work

- Browser interaction tests for import → batch karaoke → playback → save/reload → export, including mixed cached frontend/backend versions. A syntax check alone is insufficient.
- Check portrait and landscape UI, keyboard controls, errors inside dialogs, selection vs playhead, unsaved changes and recovery.
- Keep preview/export typography and timing consistent; clearly expose rendered checks while any approximation remains.
- Preserve originals and user projects, validate paths and uploads, bound expensive operations and serialize AI work.
- Mark source-only capabilities versus published releases honestly. Keep full product explanations and screenshots in README; put detailed changes in release notes.
- Test packaged and source runtimes, AI dependency availability, launcher/restart behavior and updater migrations. The optional AI requirements changed: existing v2.5.0 updater requires an installer migration for a future release.
- Publish an installer only after its actual contents and launch workflow are verified. Do not assume source tests prove packaged AI dependencies work.

## Resume checklist

1. Read this file, CAPTIONS_PLAN.md and repository instructions; inspect Git status and recent commits. Preserve unrelated user changes.
2. Phases 1 and 2 are implemented. Confirm their status below, then proceed to Phase 3 only when the user authorizes it.
3. Locate or request the intended song/SRT only if needed for evaluation. Work on a duplicate and report actual mixed-language results.
4. Run regression tests plus real browser and render checks. Clearly distinguish approximate estimates, actual alignment and manual corrections.
5. Report what works, what was tested and remaining limitations. Continue through later phases as authorized, releasing useful tested increments.

Suggested next request: “Read CREATOR_STUDIO_ROADMAP.md and proceed with Phase 3: templates, fonts and audio-reactive visuals.”

## Phase 1 implementation status

Implemented the imported-SRT whole-project karaoke action, single-line retry, language suggestions/override, review flags/counts/navigation, explicit estimates for missing lines, preserved line breaks, cancellation rollback and persisted previous-version restoration. Validated on a duplicate of the user's mixed-language song plus automated and browser/render checks; see CAPTIONS_PLAN.md. Singing timings still require listening review. Cumulative highlighting/word pop remain deferred to the animation phase. Language expansion adds 14 language choices and French/English, Korean/English and three-language modes. Automatic audio detection resolves ambiguous Latin script; mixed selections are flagged for review.

## Phase 2 implementation status

Implemented version-1 composition schema with immutable local assets, background/audio/caption tracks, clip source offsets and transforms. Song and video projects migrate without replacing their originals. Uploaded/library backgrounds, fit/fill/focus, blur/dim/tint/slow zoom, canvas ratios, loop/freeze, song trim/delay/volume/fades and optional background audio mixing are editable. Applying settings creates versioned base/preview files from a shared render specification, keeping captions synchronized; clipped lines are flagged. Added project duplication, persistent previous-composition restoration, missing-media relinking, browser caption recovery and composition setting drafts.

Delivery boundary: composition changes use Apply & preview (rendered proxy), not instant multitrack playback. Image duration matches the output; a shorter background holds its last frame. Arbitrary multitrack clip sequencing remains Phase 5. Background sources are uploads and the existing local gallery; provider search remains Phase 4. Generated versions remain on disk. Existing v2.5.0 installers have not been republished.

Validation: real FFmpeg composition/export checks, browser library background replacement and project duplication, French/Korean glyph rendering, real Whisper language detection plus alignment on generated English speech, and multilingual mocked alignment tests. French/Korean song timing accuracy still needs review with actual vocal material; no claim of listening-certified accuracy.

## Phase 3 implementation status

Implemented bundled multilingual Google Fonts (`Montserrat`, `Roboto`, `Noto Sans KR`, alongside `Oswald`, `Lobster`, `Bangers`) with OFL licenses, verified for Greek, Korean and French coverage across browser preview and FFmpeg/libass exports. Added cumulative karaoke highlighting, active word pop (115% scale), and high-contrast boxed captions. Added audio-reactive visualizer controls (Spectrum Bars vs. Waveform, Bottom/Center/Top position, height, sensitivity, and colour) with identical deterministic bar geometry between the browser `<canvas>` preview (`CaptionTiming.visualizerBars`) and ASS/FFmpeg export (`visualizer_bars`), plus composition `showfreqs`/`showwaves` support. Added 1-click aesthetic music-video presets (`Neon Karaoke`, `Cinematic Clean`, `Bold Pop`, `Minimalist Lyric`), Needleman-Wunsch lyric-to-transcription matching (`Correct transcription with my lyrics`), and localStorage lyric draft persistence.

## Phase 4 implementation status

Implemented the integrated Stock Background Browser (`#stockDialog`) supporting official Pexels and Pixabay video and photo search, orientation filtering (`portrait`, `landscape`, `square`, `all`), max-duration filtering, 5-minute TTL response caching, hover video previews, and optional local API key configuration (`/api/captions/stock/keys`) while keeping local uploads and library backgrounds working without API keys. Enforced strict HTTPS provider domain allowlists (`validate_stock_url`), redirect target validation (`_SafeRedirectHandler`), bounded streaming downloads (`<= 80 MB`) with cancellation support and magic-byte container verification (`download_stock_asset`), and full creator/license provenance retention (`validate_provenance`) stored on `studio.assets.background.provenance`.

## Phase 5 implementation status

Extended the version-1 composition schema (`creator_composition.py` and `captions.py`) and editor UI with a visual multi-lane timeline (`#videoTrackLane`, `#waveform`, `#blocks`) with snap-to-grid/playhead (`#snapTimeline`), B-roll / Picture-in-Picture overlay track (`broll` asset with start, duration, scale, X/Y position, opacity, and fade in/out), intro title cards (`title_text`, `title_duration` rendered in live preview and Layer-1 ASS subtitle export), keyframe camera pan/zoom (`keyframe_end_x`, `keyframe_end_y`), video fade-in/out transitions (`transition_in`, `transition_out`), background playback speed (`background_speed`) and cue speed rescaling (`shift_cues(..., speed)`), colour/exposure grading (`brightness`, `contrast`, `saturation`), automatic background audio ducking (`ducking`), and export quality presets (`draft` 720p proxy, `standard` HD 1080p, `high` Studio CRF 15 / 320 kbps).

## Phase 6 implementation status

Enhanced Kling Reference Prep (`reference_prep.py`, `templates/reference_prep.html`, `static/reference_prep.js`) with automatic extraction of up to 6 evenly spaced candidate frames (`candidate_0.png`..`candidate_5.png`), a composite 3×2 `contact_sheet.png`, and 1-click frame re-cutting (`POST /api/reference/<id>/select-frame`) alongside the default `first_frame.png` workflow. Added the Carousel & Still Image Studio (`/api/carousel/create`, `/api/carousel/projects`, `/api/carousel/<cid>/update`, `/api/carousel/<cid>/export`) supporting 1–30 still images, non-destructive original preservation (`orig_*`), slide reordering, 90° rotation, consistent canvas presets (`portrait` 4:5, `square` 1:1, `story` 9:16, `landscape` 16:9), safe margins, multilingual text overlays using bundled Google Fonts, and ordered ZIP export.

## Phase 7 — CapCut-style Video Filters, Visual FX & Audio FX Suite

Implemented native offline video filters, visual FX, noise cancellation, voice isolation, and audio effects across both the Captions & Lyrics Studio (`/captions` live style panel + composition editor) and the Media Tools converter (`/`):
- **Video Filters (`VIDEO_FILTERS`)**: `bw` (Black & White), `sepia` (Sepia), `vintage` (Vintage Film curves + vignette), `cyberpunk` (Cyberpunk Neon contrast/colorbalance), `warm` (Warm Golden Hour), `cool` (Cool Cinema), `dramatic` (High-Contrast Dramatic), and `dreamy` (Soft Glow).
- **Visual FX**: Cinematic Vignette (`vignette=PI/4`), Film Grain (`noise`), Sharpen (`unsharp`), and RGB Chromatic Glitch (`rgbashift`), with live browser preview on `#video` and `#stageVignette`.
- **Audio Cleanup & Effects (`AUDIO_EFFECTS`)**: FFT Noise Cancellation (`afftdn`), Voice Isolation & Speech Clarity (`highpass=100Hz` + `lowpass=7500Hz` + `afftdn` + `3kHz` presence boost + `acompressor`), plus `echo`, `concert_hall` (multi-tap reverb), `studio_vocal`, `lofi_radio`, `bass_boost`, and `chorus`.

## Phase 8 — CapCut 4-Zone Studio, Multi-Clip Storyboard & Free Video Search (Mixkit / Shorts / TikTok Grabber)

- **CapCut-Style 4-Zone Studio Workspace (`templates/captions.html`, `static/captions.css`, `static/captions.js`)**: Redesigned `/captions` into a full-viewport desktop editor with a Left Icon Dock (`🎬 Media & Clips`, `🌐 Free Videos`, `📝 Lyrics & AI`, `✨ Filters & FX`, `🎵 Audio & Voice`, `🎞️ Canvas & PiP`), Center Video Player Stage, Right Inspector (`⚡ All`, `💬 Lines & Words`, `🎨 Text Style`), and Bottom Multitrack Timeline (`🎬 Clips`, `🎵 Audio`, `💬 Lyrics`), replacing blocking modal dialogs with inline dock panes.
- **Multi-Clip Video Sequence Storyboard (`creator_composition.py`, `captions.py`)**: Added `settings.sequence` (`schedule_sequence`) supporting up to 30 video/image clips stitched via FFmpeg `concat`, with per-clip durations (`0s` Auto split song evenly or custom seconds like `10s` to cycle clips across the song), clip reordering (`←`/`→`), and multitrack timeline visualization (`#videoTrackLane`).
- **Free Video Sources Without API Keys (`_search_mixkit`, `_search_youtube`) & Social Clip Grabber (`POST /api/captions/stock/grab-url`)**:
  - **🔥 Mixkit HD Stock (`mixkit`)**: Built-in zero-key search for 1,370+ free HD dance and aesthetic stock videos (`-720.mp4`).
  - **📱 YouTube Shorts / Google (`youtube`)**: Built-in zero-key vertical video search via `yt-dlp`.
  - **🔗 Direct TikTok / Reel / Short Clip Grabber**: Paste any TikTok dance video, Instagram Reel, or YouTube Short URL directly in the studio to download without watermark and append to the clip sequence.
  - **1-Click Dance & Vibe Chips**: Instant category pills (`💃 Dance`, `🔥 Street / Hip-Hop`, `🪩 Club & Party`, `💃 Modern Dance`, `✨ Neon Aesthetic`, `🌆 Night Drive`, `🎤 Concert / DJ`, `🌊 Sunset Vibe`).
