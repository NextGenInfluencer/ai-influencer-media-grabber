# v2.6.0 code, security, UX and regression audit

> Follow-up: local v2.6.1 stability work now addresses the broken grabber, URL/destination safeguards, managed download/search cancellation and deadlines, active-job tracking, and silent cycling truncation. See the Unreleased changelog and `tests/test_stability.py`. This document retains the original v2.6.0 findings; remaining editing, stock metadata and preview-consistency items are still open. No installer/release has been published for these fixes.

Audited 2026-10-21. Local HEAD and tag `v2.6.0` resolve to `74a10e39acdcfa5b672354daaf5e156641cd4929`. Working tree was clean. This is an audit, not a patch release; application source was not changed.

## Assessment

The application has a substantial working foundation, but the claim that all Creator Studio phases are complete and verified is too strong. The new social clip grabber is broken in the released code. Additional defects affect clip scheduling, editing semantics, download safeguards and stock metadata. Fix these before expanding the editor further.

The protected project `6e4dacd26f0e41cd8bb0299b64e7adb2` was not opened, modified or deleted. Browser testing used a separate server on port 5094 with `MEDIA_GRABBER_DATA_DIR` pointing inside `audit_artifacts/v260_browser`. Generated media and route checks used `audit_artifacts/v260_fixtures`. No real private-network requests were made.

## Findings, in priority order

### 1. P1 — Social clip grabber fails before every download

**Location:** `captions.py:1545`, imports at line 16.

`_grab_social_video()` calls `cast(Any, ydl_opts)`, but only `Any` is imported from `typing`. A valid YouTube URL returns `Could not grab video from URL: name 'cast' is not defined`. The same helper handles YouTube stock-result downloads, so those are affected too.

**Evidence:** Reproduced through both a Flask test client and the actual browser's Grab & Add button. Screenshot: `audit_artifacts/v260_fixtures/grabber-error.png`.

**Fix:** Import/remove `cast`, then add a route-level regression test that reaches a mocked downloader and returns a real fixture file. The existing search/provenance tests do not exercise this path.

### 2. P1 — URL validation permits private-network targets once the grabber is repaired

**Location:** `captions.py:1561–1572`.

The social route rejects only four literal local hostnames/addresses. It accepts arbitrary HTTP(S) hosts, ports and internal addresses, despite asking for TikTok, Instagram or YouTube URLs. It then delegates to yt-dlp, including its generic extractor. This creates a server-side request risk from user-supplied links.

**Evidence:** After supplying the missing `cast` only in test memory, mocked downloader calls received `http://127.0.0.2:8080/private`, `http://192.168.1.1/private`, and the link-local metadata address. No network request was executed. In the unmodified release, finding 1 prevents reaching this code.

**Scope:** The normal app has session/origin/token protections; this is not evidence of an unauthenticated remote exploit. Those protections do not validate the destination of an authorized download.

**Fix:** Restrict this particular feature to supported platform hosts and HTTPS, reject credentials/unexpected ports, and enforce safe destinations through redirects/extraction. If arbitrary sites remain supported, implement explicit private/reserved-address and redirect protections. Repair this alongside finding 1.

### 3. P2 — Social downloads lack cancellation, total bounds and active-job accounting

**Location:** `captions.py:1527–1559`; `creator_composition.py:534–551`.

`begin_job()` records cancellation state; it does not itself cancel yt-dlp. The helper supplies no progress hook checking cancellation and does not use the application's managed subprocess wrapper or active-job callbacks. `socket_timeout=25` limits individual socket operations, not the whole job. There is no file-size, live-stream or total-duration bound, and partial files are not cleaned up here. YouTube search also lacks explicit timeout/cancellation controls. The regular bounded stock downloader has stronger protections, but its route also omits active-job counting.

**Evidence:** Code review and captured downloader options. This was not tested by starting an intentionally large live download.

**Fix:** Use the shared job lifecycle, cancellable downloader hooks/worker, overall deadline, size/duration limits, live-stream rejection and partial-file cleanup. Test Stop during download, search and merge, plus exit/update while busy.

### 4. P2 — Clip cycling silently stops early

**Location:** `creator_composition.py:167–204`.

Scheduling stops at 20 passes or 60 segments, then stretches the final segment over all remaining time. With two one-second clips and a 213-second song, the result contains 40 segments; the final one starts at 39 seconds and lasts 174 seconds. This contradicts the cycling control. A single clip's custom duration is also replaced by the whole song duration.

**Evidence:** Executed scheduler reproduction, saved in `audit_artifacts/v260_fixtures/results.json`.

**Fix:** Render a reusable cycle and repeat it, or schedule the complete timeline within an explicit supported limit. Do not silently change duration to enforce a resource cap. Test long songs, 30 short clips, mixed auto/custom durations, single clips and loop disabled.

### 5. P2 — Changing or disabling an effect cannot undo an already baked effect

**Location:** `captions.py:1415–1427`; `static/captions.js:268`; composition-render effect synchronization.

Composition generation bakes effects into the new source and copies their values into caption style. Export avoids duplicating an unchanged effect, but a changed effect is applied over the already processed source. After baking black-and-white, selecting None cannot restore colour; selecting another filter stacks it over grayscale. The same issue applies to baked audio effects/cleanup.

**Evidence:** Code-path review. A dedicated pixel/audio comparison of this transition remains a regression test to add; the existing tests confirm effects render, not that they can be removed.

**Fix:** One authoritative effect state rendered from original assets. Changing an effect must rebuild the relevant preview/source, or the UI must explicitly offer a rebuild rather than imply a reversible live edit.

### 6. P2 — Multi-clip backgrounds silently lose their audio

**Location:** `creator_composition.py:335–339`.

Background audio is mixed only when `not multi_clip`. A multi-clip sequence ignores a nonzero background-volume setting. For single videos, background playback speed changes video timestamps without applying matching tempo changes to background audio, risking synchronization drift.

**Evidence:** FFmpeg graph inspection. The real mixed-media check intentionally used silent backgrounds and passed; it does not validate clip audio.

**Fix:** Either support timed per-clip audio concatenation with silence for audio-less clips, or disable the unsupported controls with a clear explanation. Align audio speed with video speed.

### 7. P2 — Stock cards report invented metadata and unverified licensing

**Location:** `creator_composition.py:490–528`, `534–582`, `validate_provenance()`.

Mixkit results hardcode 15 seconds, derive claimed video dimensions from thumbnail shape, manufacture a `-720.mp4` URL, use a generic catalogue source link, and label every result with the Free License. Creator is also hardcoded. These are not verified item metadata. The official [Mixkit license page](https://mixkit.co/license/) distinguishes Free and Restricted stock-video licenses; the app must retain the applicable item-level information rather than assume it.

YouTube results invent dimensions from the requested orientation and use a 15-second duration when unknown. `max(max_duration,65)` allows results longer than a user's smaller duration limit. “YouTube / Google” performs YouTube search only, and its stored license value is a provider label, not evidence of reuse permission.

**Evidence:** Code review; browser Mixkit search returned 24 cards displaying the hardcoded dimensions/license. This establishes that search currently works, not that every media URL or license is correct.

**Fix:** Preserve item URLs and actual provider metadata; mark unknown values as unknown; probe downloaded media; respect duration filters; distinguish reference videos from verified stock assets. Rename the YouTube source accurately. Make Mixkit parsing robust to attribute order/layout changes and distinguish provider failure from zero results.

### 8. P2 — Visualizer implementations do not all share identical math

**Location:** `static/captions.js:18–64`; `captions.py:visualizer_bars`; `creator_composition.py:391–402`.

The caption overlay builds bars from nearby waveform-envelope samples. Composition rendering uses FFmpeg `showfreqs` (frequency analysis) or `showwaves`. These are different signals and rendering algorithms. Matching the JavaScript and Python bar functions does not establish parity with the composition visualizer. A waveform-derived decorative spectrum is also not a measured frequency spectrum.

**Evidence:** Implementation comparison; no frame-by-frame parity proof for all paths. Existing parity tests cover a narrower claim.

**Fix:** Define a single analysis/render specification, or clearly separate the decorative caption visualizer from the composition audio visualizer. Add deterministic image comparisons across preview and export.

## UX and architecture gaps

- Video/B-roll timeline blocks are clickable summaries; their handlers seek/open settings. They are not fully draggable/trimmable media tracks. Caption blocks do support timing interaction. Describe the capability accurately and prioritize real media trim/split/move controls next.
- Sequence edits live in `clipSequence` until Apply; caption save/history does not include that sequence. Add an explicit unsaved sequence indicator and draft recovery before presenting Save as covering every edit.
- “Voice isolation” is filtering, denoising, EQ and compression, not learned vocal/stem separation. Label it speech cleanup or add a genuine optional separation engine. Likewise, tempo-compensated “slowed”/“nightcore” presets should explain that they mainly change pitch.
- Full 1080p composition renders precede preview generation, and repeated sequence occurrences each open a separate FFmpeg input. Add lower-resolution proxies and reuse cycle segments to keep editing responsive.
- The four-zone desktop screen and song-creation drawer worked in the tested browser. Small-window accessibility, keyboard-only use, and low-resolution displays still need a dedicated pass.
- Carousel updates write replacement slide images in place before saving project metadata (`reference_prep.py:478–484`). A late render/write failure can leave old metadata with partially updated outputs. Stage a complete set and atomically publish it; keep originals unchanged.
- Lyric matching allocates full similarity, score and traceback matrices and repeatedly normalizes cue text. Bound work, precompute normalization, and consider banded alignment/cancellation for large inputs. No large-input exhaustion test was run.

## Verification and positive findings

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -v` using project venv | 85 tests passed, 31.162 seconds |
| `node --check static/captions.js` | Passed |
| `node tests/test_caption_timing.js` | Passed |
| `node tests/test_stream.js` | Passed |
| Real FFmpeg mixed portrait/landscape/still concat | Passed; short audio-less videos extended correctly, red/blue/green samples in order |
| Browser: home → captions → Create from Song | Passed with generated three-second WAV and isolated storage |
| Browser: 5s Check | Completed and opened rendered-preview dialog; short source correctly remains three seconds |
| Browser: Mixkit search | Returned 24 results |
| Browser/API social grab | Failed reproducibly with missing `cast` |
| Long-song clip cycling | Failed expected cycling behavior |
| Private URL rejection | Fails after bypassing missing import in test memory only |

The official-provider stock downloader validates HTTPS hosts/redirects, checks container signatures and bounds streams at 80 MB. Composition asset handling uses generated local names and validates existing asset references. The updater validates archive paths, symlinks, duplicates and size/count bounds, stages code and maintains rollback state; its automated tests pass. These are useful protections worth preserving.

`carousel_studio.py` does not exist at this commit. Carousel functionality is implemented in `reference_prep.py`; this is a documentation/build-list mismatch, not proof that the feature is absent. `build_staging.py` silently skips the nonexistent entry. It does include `caption_fonts` and the relevant existing modules.

The installer script declares 2.6.0 and a local `dist/AI-Influencer-Media-Grabber-v2.6.0-Setup.exe` exists (116,483,333 bytes). Installer presence is not proof of clean-install correctness or equivalence to the published GitHub binary. No installer was run on the user's machine, no remote release byte comparison was performed, and no actual application update was applied.

## Recommended next work

1. **2.6.1 stabilization:** repair the grabber, destination validation, cancellation/resource limits and their route tests together. Fix cycling and add real long-sequence render tests.
2. **Editing correctness:** make effects reversible from originals, resolve sequence audio/speed semantics, stage carousel output atomically, persist unsaved sequence edits.
3. **Trustworthy media browser:** verified metadata/provenance, honest provider labels, resilience tests, clear failure states and cancellable jobs.
4. **Preview consistency:** one visualizer specification, multilingual preview/export visual tests, proxy previews and consistent effect controls.
5. **Then expand the free editor:** actual clip trim/split/reorder timeline, per-clip audio controls, fades between clips, reusable templates and optional genuine vocal separation.

Release acceptance should include a clean Windows install and upgrade from the previous version, old-project migration, all six bundled fonts with Greek/Korean/French samples, real lyric-correction review on synthetic projects, cancellation during search/download/merge/render, and export verification from UI-created sequences. These were not all covered by this audit; the passing unit suite must not be treated as their substitute.

Reproduction script: `audit_artifacts/v260_checks.py`. Evidence directory is ignored by Git. This report is the only new tracked candidate; no application source changes were made.
