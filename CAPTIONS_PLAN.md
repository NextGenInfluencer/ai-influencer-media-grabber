# Captions & Lyrics implementation

Build a local editor alongside the existing downloader and Media Tools. Keep source media intact and store projects under the user's media library. This is a focused caption editor, not a full multitrack video editor.

## First usable release

- Video upload or library selection; browser-compatible preview proxy and waveform.
- Automatic Whisper transcription with word timestamps; optional language selection.
- Pasted lyrics with clearly marked estimated timings; SRT/LRC import and SRT export.
- Editable caption blocks, drag/resize timing, split/merge/delete, line looping, playback speed, shift-all timing, undo/redo and autosave.
- Live styling: font, size, color, outline, position, backgrounds, presets and karaoke highlighting. Greek and English text supported.
- Editable word timings; invalidate word timings when text changes instead of pretending they remain aligned.
- Shared project coordinates for live and final rendering. A short FFmpeg-rendered preview checks actual export appearance; browser typography is an approximation.
- Save reusable styles; optional safe-area guides.
- Export a new H.264 MP4 using ASS subtitles; never overwrite the input.
- Apply the existing local authentication, path validation, job cancellation and AI serialization. Validate all project fields, escape subtitle markup, and snapshot projects for exports.

## Follow-up work

- Evaluate the implemented stable-ts lyric alignment on real Suno and other songs. Uniform manual estimates remain separate from audio alignment.
- Editable background/audio layers with an audio offset, integrated stock search/import, vocal separation, animated text presets, and long-media performance refinements.
- A larger transcription-model selector after compatibility and resource testing.

## Validation / release gate

Test Unicode and multiline subtitle imports, malformed times, overlapping cues, ASS markup escaping, word timing validity, autosave conflicts, real FFmpeg rendering, original preservation, cancellation, and project reload. Check the browser at portrait and landscape dimensions. Run the existing regression suite and JavaScript syntax checks. Evaluate automatic transcription on actual speech/song samples separately; deterministic fixtures cannot certify recognition accuracy. Bundle new modules in the installer and updater allowlist; do not publish until these checks pass.

## Implemented in v2.5.0

The first usable release above is implemented. 46 Python tests pass in the development environment and the bundled Python 3.13 runtime; caption JavaScript syntax and existing stream checks pass. New tests cover Unicode/SRT/LRC parsing, invalid/overlapping timestamps, word-text consistency, ASS injection prevention, karaoke gaps, save conflicts, blocked external paths, real media preparation/transcription-fixture/export, and original preservation.

Browser checks used isolated portrait and landscape test videos and mixed Greek/English text. Confirmed paste, styling, word timing controls, preview rendering, full export, reopening, resizing blocks, undo and autosave. A generated export frame was visually checked for Greek glyphs. Real vocal recognition and automated alignment of supplied lyrics are not certified by these checks. Automatic lyric alignment remains follow-up work; this version labels pasted timings as estimates.

The v2.4.1 source updater will reject an archive that imports the new module without including it, because its old allowlist omits that file. Use a new installer for the first captions release; the updated allowlist supports subsequent updates.

## Source upgrade after v2.5.0

Implemented supplied-text alignment with stable-ts 2.19.1 using the existing shared Whisper model. Language and audio-range selection, section-label removal, preserved line breaks/repeated lyrics, validated word timing and cancellation without replacing saved captions. Installed and exercised the real aligner locally with generated speech; song accuracy still needs real vocal samples.

Implemented song-to-video creation (MP3/WAV/M4A/FLAC/OGG), 1080p portrait/square/landscape, colour/photo/looped-video backgrounds from upload or library, and optional audio-reactive waveform. Composition is prepared into the base video, not an editable multitrack timeline. Original audio/background uploads are retained. Added three locally bundled Google Fonts with licenses. Stock-library links are discovery links only, not API search/import.

The optional AI requirements changed. A future packaged release needs an installer; do not promise that the v2.5.0 source updater can apply this dependency migration. The local source environment already has the new dependency.

## Phase 1: imported-SRT karaoke (source)

Whole-project and single-line word alignment preserve subtitle text, line breaks, line boundaries and style. Uses constrained stable-ts align_words with one shared Whisper model and bounded cue audio slices. Per-line Greek/English suggestions and explicit overrides, review flags, progress, selected retry, manual review and explicit estimates for missing lines are available. Changes are staged in memory; cancellation rolls back caption state. A persisted prior-caption snapshot supports restoration after reload.

Real evaluation on a duplicate of the user’s 57-line mixed Greek/English project: 53 lines unflagged, four review flags, two missing word timings (one failed line already had prior timings). All text and line timestamps preserved; original project bytes unchanged. These counts verify operation and timing checks, not listening-certified accuracy. Browser whole-song and single-line actions completed; actual rendered output visibly highlights the previously reported English line.

## Phase 2 and multilingual expansion (source)

See CREATOR_STUDIO_ROADMAP.md and README.md for editable composition controls and versioned project architecture. Added 14 language choices and constrained French/English, Korean/English and three-language karaoke modes. Source updater and installer staging include creator_composition.py. No new AI dependencies were introduced in this phase. Composition previews are prepared with Apply & preview; instant multitrack editing remains future work.

Validation: 63 Python tests pass in the bundled runtime; source-runtime regression tests and JavaScript checks also pass. Browser Apply & preview, duplicate and actual caption export succeeded. Real rendered French/Korean text displays correctly; audio-delay rendering was checked against waveform samples. Only isolated test projects were changed.

## Phase 3: multilingual fonts, lyric animations, spectrum visualizer and presets (source)

Bundled `Montserrat`, `Roboto` and `Noto Sans KR` with OFL licenses in `static/fonts/`, giving full local Greek, Korean and French glyph support across live preview and FFmpeg ASS exports. Added cumulative karaoke highlighting, 115% active-word pop, and high-contrast rounded backdrop boxes. Added an audio-reactive visualizer (Spectrum Bars and Waveform, Top/Center/Bottom position, height, sensitivity and colour) using shared deterministic geometry between the browser stage canvas and ASS/FFmpeg rendering. Added 1-click music-video presets (`Neon Karaoke`, `Cinematic Clean`, `Bold Pop`, `Minimalist Lyric`) and `Correct transcription with my lyrics` sequence alignment with draft persistence.

## Phases 4, 5 and 6: stock background browser, multitrack overlays, carousel studio & Kling contact sheets (source)

- **Phase 4 (Stock Background Browser):** In-app Pexels and Pixabay video/photo search (`/api/captions/stock/search`), orientation/duration filters, redirect-validated and size-bounded (`<= 80 MB`) downloads with magic-byte container checks (`/api/captions/stock/download`), optional local API key storage (`/api/captions/stock/keys`), and persistent creator/license provenance on `studio.assets.background.provenance`.
- **Phase 5 (Multitrack Short-Video Editor):** Multi-lane track view (`#videoTrackLane`, `#waveform`, `#blocks`) with timeline snapping, B-roll / PiP overlay track (`broll` asset with timing, scale, position, opacity and fades), intro title card overlay, keyframe camera pan/zoom, video fade-in/out transitions, colour/exposure grading (`brightness`, `contrast`, `saturation`), background speed and audio ducking, plus `draft`/`standard`/`high` render quality presets.
- **Phase 6 (Carousel Studio & Kling Frame Selector):** Contact sheet (`contact_sheet.png`) and candidate frame selector (`/api/reference/<id>/select-frame`) alongside the default `first_frame.png` Kling workflow, plus the multi-slide Carousel & Still Image Studio (`/api/carousel/*`) with slide reordering, 4:5 / 1:1 / 9:16 / 16:9 canvas presets, safe margins, rotation, multilingual text overlays and ordered ZIP export.
- **Phase 7 (CapCut-Style Video & Audio Effects Suite):** Added 8 video color filters (`bw`, `sepia`, `vintage`, `cyberpunk`, `warm`, `cool`, `dramatic`, `dreamy`), visual FX (`vignette`, `film_grain`, `sharpen`, `chromatic` RGB shift), FFT noise cancellation (`noise_cancel`), voice isolation (`voice_isolation`), and 6 audio effects (`echo`, `concert_hall`, `studio_vocal`, `lofi_radio`, `bass_boost`, `chorus`) across both the Captions & Lyrics Studio and Media Tools converter. 82 Python tests and all JavaScript checks pass.
