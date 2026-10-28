# Creator Studio reliability roadmap

## v3.1.4: implemented stability milestone

- Disposable test storage initialized before importing application modules.
- Shared installer/OTA application manifest; compatibility with older updater allowlists.
- A metadata backup before the first project save in this version, plus existing composition and karaoke restore points.
- Source-position-aware clip splitting, repeated-cycle splitting within the 30-clip limit, source-start editing, and single-clip speed.
- Undo/redo for clip-card changes and split operations; non-upload sequence drafts retained in the browser. Newly selected upload files must be selected again after a browser restart.
- Silent/short audio segment padding and actual render tests for all supported transitions.
- Original-asset, single-pass composition exports and selected 30/60 fps output.
- Separate live sticker overlays, exported pop/fade/slide/static animations, and character-level karaoke typewriter export.
- CPU export override, bounded CPU retry on recognized encoder failures, and completed encoder reporting.
- User-data font storage, legacy font preservation, unique filenames, and rejection of conflicting family replacements.
- Interrupted per-line karaoke jobs have resumable checkpoints, and uncertain lines can be retried separately. Checkpoints are rejected after text, timing, audio, or language changes.
- Lyric correction preserves unchanged word timings. Correction/alignment respects selected ranges and preserves unrelated captions.
- More accurate quality, beat-suggestion, and background permission labels.

## Verification boundaries

Synthetic videos verify source positions, audio duration, transition success, and sticker appearance. Automated lyric tests cover preservation and range handling, including Greek, French, Korean, and English text. These do not establish singing-alignment accuracy for every real song. Review estimated or low-confidence timings while listening.

Live browser preview remains an approximation for some filter effects, font rasterization, glow, and animation easing. The five-second rendered check and final export share the export path. Source media remains separate from edits. Old prepared previews may need Apply before showing the corrected sticker behavior.

Measured coverage is not 100%; the audit exposed a previously unmeasured baseline. Coverage reports distinguish tested caption/composition behavior from less-covered application/download integrations.

## v3.1.5: lyric review and anchored section recovery

Implemented: editor proposals for correction/alignment, before/after text, per-line listening, Apply/Discard/Review later, stale-project protection, and restore points. Alignment checkpoints a successful initial pass, refines short sections from those anchors, keeps successful sections, and resumes after interruption. Failed refinements retain and flag first-pass timing.

Limits: the first whole-range pass still needs reliable anchors and must finish before recovery. It cannot automatically recover an entirely unalignable song. The first pass uses one selected language; mixed-language material still needs matching sections. No representative real-song accuracy benchmark has been completed. Confidence labels are review flags, not calibrated probabilities.

## Remaining workflow milestone

1. Automatic sectioned lyric alignment with intermediate recovery and retained successful sections, verified against representative sung material in all supported language combinations.
2. A review screen showing proposed lyric replacements and confidence before applying. Optional local-LLM assistance may match text; timestamps must come from audio or existing timing.
3. Further parity work for all live filter, visualizer, and animation previews, with broader frame-comparison fixtures.
4. Complete undo/draft support for every composition setting and media-upload draft persistence.
5. Broader download-provider, GPU-family, and clean-install testing, plus expanded application coverage.

These items are not described as complete by the v3.1.4 release. Keep them separate from the verified stability fixes so users can rely on the release notes.
