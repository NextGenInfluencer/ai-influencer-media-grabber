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

- Automatic alignment of supplied lyrics to singing: evaluate with real Suno and other songs before selecting or bundling an aligner. Uniform estimated timings are not audio alignment.
- Separate song audio with an offset, vocal separation, advanced text animation, and long-media performance refinements.
- A larger transcription-model selector after compatibility and resource testing.

## Validation / release gate

Test Unicode and multiline subtitle imports, malformed times, overlapping cues, ASS markup escaping, word timing validity, autosave conflicts, real FFmpeg rendering, original preservation, cancellation, and project reload. Check the browser at portrait and landscape dimensions. Run the existing regression suite and JavaScript syntax checks. Evaluate automatic transcription on actual speech/song samples separately; deterministic fixtures cannot certify recognition accuracy. Bundle new modules in the installer and updater allowlist; do not publish until these checks pass.

## Implemented in v2.5.0

The first usable release above is implemented. 46 Python tests pass in the development environment and the bundled Python 3.13 runtime; caption JavaScript syntax and existing stream checks pass. New tests cover Unicode/SRT/LRC parsing, invalid/overlapping timestamps, word-text consistency, ASS injection prevention, karaoke gaps, save conflicts, blocked external paths, real media preparation/transcription-fixture/export, and original preservation.

Browser checks used isolated portrait and landscape test videos and mixed Greek/English text. Confirmed paste, styling, word timing controls, preview rendering, full export, reopening, resizing blocks, undo and autosave. A generated export frame was visually checked for Greek glyphs. Real vocal recognition and automated alignment of supplied lyrics are not certified by these checks. Automatic lyric alignment remains follow-up work; this version labels pasted timings as estimates.

The v2.4.1 source updater will reject an archive that imports the new module without including it, because its old allowlist omits that file. Use a new installer for the first captions release; the updated allowlist supports subsequent updates.
