# AI Influencer Media Grabber — audit

Date: 19 October 2026. Reviewed source version: 2.3.

The app already covers a useful workflow: collecting references, converting media, extracting frames, transcription, and finding saved material. The main priority is making those operations predictable and protecting originals. Adding more AI features before fixing the issues below would increase the number of ways a job can silently produce the wrong result.

## Scope and evidence

Reviewed backend routes, download and conversion pipelines, cleaner, prompt generator, frontend JavaScript and markup, dependencies, launchers, installer builder, update mechanism, and documentation. Reviewed the supplied converter screenshot; it depicts v1.9, so visual observations are provisional rather than a live v2.3 usability test.

Ran isolated Flask route checks and real FFmpeg/Pillow processing on generated fixtures. To avoid startup dependency upgrades and writes to the real media library, the checks load selected backend functions from the source syntax tree and redirect their home directory into `audit_artifacts`. No personal media was processed. Python source parsing and both inline JavaScript blocks passed syntax checks.

Evidence: `audit_artifacts/results.json`; repeatable diagnostic script: `audit_checks.py`. These are diagnostic reproductions, not a comprehensive automated regression suite. Application source was not changed.

Not exercised: live downloads with authenticated social accounts, actual model inference or model installation, long-running concurrency stress, a fresh Windows installer deployment, live browser interaction, or a real update installation. Those remain release-validation tasks. Static findings below are identified separately from reproduced behavior; this audit cannot certify that every possible defect has been found.

## Fix first: security and file safety

### 1. File access is not restricted to approved locations — high priority, reproduced

`app_local.py:732`, `1808`, `1918`, `1985`.

`is_safe_path` rejects the Windows directory but otherwise allows almost any path. The preview endpoint returned a benign test file outside the media library. The media endpoint also returned it when given an absolute Windows drive path: joining that path discards the intended base directory. Delete and open-file routes depend on the same permissive helper; open-file can launch executable file types.

Localhost binding is a useful protection, but it is not authentication. There is no session token or host/origin validation on these routes. This does not mean every remote website can immediately read local files: browser restrictions still matter. It does mean that a same-origin script injection or another local client has excessive access.

Fix: use opaque file IDs, resolve paths and validate containment in explicitly approved roots, reject drive/UNC escapes and unsafe file types, and authorize selected external files separately. Add per-session request protection and host/origin checks. Keep binding to localhost. Follow the [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/).

### 2. Uploaded conversion filenames can escape the output folder — high priority, reproduced

`app_local.py:906`, `948`.

The output basename comes directly from the multipart filename. A test upload named `../escaped.mp4` successfully wrote a converted file outside `Conversions`, within the isolated audit directory. Normal file pickers generally supply simple names, but the server must validate requests itself.

Fix: normalize and sanitize the basename, require an allowed output format, generate collision-resistant names, and validate the resolved destination before writing. Use temporary outputs and atomic finalization.

### 3. Remote metadata is inserted as HTML — high priority, source finding

`templates/index.html:1629`, `1648`, `1905`.

Preview titles, uploader names, thumbnail URLs, and entered URLs are interpolated into `innerHTML`. A crafted remote title can become active markup. This is more consequential because the page can call powerful local file APIs. An escaping helper exists elsewhere but is not consistently used.

Fix: build nodes and assign `textContent`; validate URL protocols and set image/link properties explicitly. Add a restrictive content security policy after moving inline scripts/handlers into bundled assets. No exploit was executed during this audit.

### 4. Failed recycle-bin operations silently become permanent deletion — high priority, source finding

`app_local.py:1991`.

If `send2trash` fails for any reason, the code calls `os.remove`. A recoverable delete can unexpectedly become irreversible.

Fix: report the failure and leave the file alone. Offer permanent deletion only as an explicit separate action; provide an undo/recovery workflow.

### 5. Cleaner collisions and backups are unreliable — high priority, source finding

`cleaner.py:96`, `203`, `234`, `263`.

Two individually selected files with the same basename share a destination and can overwrite each other during copying. Photo numbering only considers the current batch, not all files already on disk. Backups also use basenames only; an existing backup suppresses a new backup, and backup errors are swallowed. The downloader's cleaning option then edits the downloaded file in place.

Selecting a folder that includes the cleaner's own output also allows previous results to be picked up again. Deduplication records source paths, so changed content at the same path can be skipped.

Fix: unique output IDs, preserved source-relative structure, content hashes, explicit output-directory exclusion, and verified backups before any in-place operation. Keep originals immutable and save edits as versions.

## Editing correctness

### 6. Fast trimming ignores other requested work — high priority, reproduced

`app_local.py:963`.

A generated H.264 clip submitted with H.265 output, trim, and subtitle export returned success but remained H.264 and produced no SRT. The fast path uses stream copy and immediately continues, bypassing later subtitle and codec processing. It also permits an MP4/H.264 selection to retain an incompatible source codec.

Fix: separate codec-preserving trimming from conversion, and run requested sidecar operations independently. Only copy streams if the actual input codecs meet the selected output contract.

### 7. “Frame-accurate” and “bit-exact” claims are too broad — medium priority, source finding

`app_local.py:972`, `1006`, `1041`, `1143`; `templates/index.html:358`.

Fast stream-copy cuts are constrained by seek points. The UI's Set Start/End controls also floor times to whole seconds. Other routes convert to 8-bit YUV420 and AAC and may encode intermediate files before final output. CRF 0 therefore does not make the complete workflow a bit-exact copy of the source, especially for audio, HDR, or previously processed video.

Fix: expose “Fast cut” versus “Exact cut,” preserve subsecond selections, describe lossless modes accurately, and build one filter pipeline to avoid unnecessary intermediate encodes. See [FFmpeg's seeking documentation](https://www.ffmpeg.org/ffmpeg.html).

### 8. Several aspect-ratio crops fail on valid inputs — high priority, reproduced

`app_local.py:1025`, `1035`.

The 4:5 crop always derives width from full source height. A 100×200 portrait image requests a 160×200 crop, wider than the source, and FFmpeg fails. Similar assumptions affect 9:16 and 16:9 crops in the opposite input orientation.

Fix: derive the largest rectangle of the target aspect ratio that fits inside both source dimensions. Show the actual crop before export and allow manual positioning.

### 9. Cleaner destroys GIF animation — high priority, reproduced

`cleaner.py:109`, `142`.

A two-frame GIF became a single-frame image while reporting success. The code processes and saves only one frame. Animated WebP and multipage formats need similar handling.

Fix: preserve all frames, durations, loop/disposal settings, and transparency, or clearly reject unsupported animated inputs before processing.

### 10. Cleaner writes MP4 data under other video extensions — high priority, reproduced

`cleaner.py:35`, `60`.

A `.webm` file was rewritten with an MP4 container but kept its `.webm` extension. The implementation always creates a temporary MP4 then replaces the original path. This can confuse importers and players; copying audio into MP4 can also fail for some codecs.

Fix: explicitly choose an output container and matching extension, validate streams, and keep the original intact.

### 11. Removing EXIF can turn portrait photos sideways — medium priority, reproduced

`cleaner.py:109`.

A JPEG carrying rotation in its EXIF metadata lost that metadata without rotating its pixels. The result was landscape instead of the intended portrait orientation. Color profiles also are not explicitly preserved through the array reconstruction.

Fix: apply EXIF orientation before stripping metadata; preserve or deliberately convert color profiles. Handle small images and unsupported HEIC decoding explicitly.

### 12. Output settings do not match their labels — medium priority, source finding

`app_local.py:1059`, `1156`; `README.md`.

“1080p” uses a portrait 1080×1920 bounding box, so landscape footage can end up around 1080×608 instead of 1920×1080. Compression percentages are CRF selections, not size guarantees. GIF output uses 15 fps without palette generation or a target-byte loop. PNG output extracts one frame rather than the frame sequences advertised in the README.

Fix: orientation-aware dimensions, honest estimated size labels, a real “under X MB” mode, GIF palette optimization, adjustable frame rate and looping, and separate “single frame” and “frame sequence” exports.

## Jobs, downloads, and reliability

### 13. Long jobs can report timeout while continuing — high priority, source finding

`app_local.py:1207`, `1731`.

After an “Encoding” or model-processing update, the stream waits only 120 seconds for another queue item. FFmpeg and inference can take longer without producing another message. The UI then receives a timeout while the worker continues writing files. Retrying can launch duplicate work.

Fix: persistent job IDs, independent status/progress endpoints, periodic stream heartbeat events, and a bounded worker queue. A lost stream must not define whether a job succeeded.

### 14. Progress events can disappear at network chunk boundaries — medium priority, reproduced algorithm

`templates/index.html:1728`, `2095`, and cleaner stream readers.

Readers split each received chunk directly instead of buffering incomplete events. Splitting a valid completion event across two chunks resulted in zero parsed events using the same algorithm. UTF-8 characters can also split across chunks.

Fix: a shared buffered SSE parser and streaming text decoder; retain incomplete frames until more bytes arrive. Treat an ended stream without a terminal job status as interrupted, not successful.

### 15. Cancellation and shutdown do not cover all work — high priority, source finding

`app_local.py:1218`, `1338`, `1419`, `1720`, `1926`, `2229`.

Cancellation is mainly checked in downloader progress callbacks and gallery-dl output reads. FFmpeg, model inference, and converters lack full cancellation. Disconnect cleanup removes cancellation flags while a worker can still be active. Cleaner jobs and prompt extraction are not counted by `is_busy`, so the watchdog can exit during those operations if heartbeats stop. Explicit Exit/Restart also do not drain jobs.

Fix: one job manager for every operation, cancellation tokens plus subprocess handles, guaranteed cleanup, and a clear close-while-working choice. Do not rely only on browser timer cadence.

### 16. Some failed operations still look successful — high priority, source finding

`app_local.py:1661`, `1685`, `1705`, `1712`.

Several subprocess return codes are ignored. The H.264 replacement accepts mere file existence; a partial output can replace the source. The outer download exception handler does not increment `failed_count`. The frontend displays “Completed!” for any `done` event, including partial-failure batches.

Fix: check return codes, validate output duration/streams, and atomically promote only verified files. Report success, partial success, failure, and cancellation distinctly, with per-file results.

### 17. Playlist and photo fallback skip downstream options — medium priority, source finding

`app_local.py:1430`, `1460`.

Playlist/multi-video results return to the loop before normal per-file processing. The gallery-dl fallback likewise skips transcription, prompt extraction, frames, and other selected steps, and records a folder rather than each downloaded item. Source tracking becomes weaker for precisely the carousel/reference workflow you use.

Fix: normalize every downloader result into individual media records, then run the same processing pipeline per file. Clearly report which features apply to images versus video/audio.

### 18. Gallery and history can disagree with the filesystem — medium priority, source finding

`app_local.py:129`, `171`, `1750`.

Gallery scanning is hardcoded to the default library even though downloads allow a custom folder. WAV exports are omitted. Clear/delete history can be undone by importing the workspace history again or reconciling media files back into history. Full recursive scans and per-item source lookups become expensive as the library grows; all results are rendered without pagination.

Fix: an indexed media database with approved library roots, stable IDs, deletion markers, paginated queries, thumbnails, and linked sidecars. Separate “clear activity history” from “rescan/import media.”

## AI, privacy, and maintenance

### 19. The anti-detection promise is unverified — high product priority

`cleaner.py:38`, `75`; `README.md`; cleaner UI.

The implementation crops, adds noise, rewrites metadata, and can inject invented iPhone metadata. There is no detector evaluation or verification that SynthID was removed. Metadata removal does not establish that a file will be classified as camera-origin content. Google's [SynthID documentation](https://deepmind.google/models/synthid/) and [image watermarking explanation](https://deepmind.google/blog/identifying-ai-generated-images-with-synthid/) describe resilience to common edits.

Recommendation: repurpose this tab as “Metadata & Export.” Provide before/after metadata inspection, privacy stripping, explicit quality controls, and preservation of originals. Remove guaranteed bypass claims and invented camera provenance as a default workflow. This is a product-accuracy recommendation; the audit did not test proprietary detectors.

### 20. Prompt extraction is a generic caption, not recovery of an original prompt

`ai_prompter.py:62`; `app_local.py:1887`.

The app captions one image using BLIP and wraps it in generic text. Video extraction selects frame zero even where a comment says “middle frame.” The gallery endpoint does not apply the optional LLM enhancement used by the downloader. Errors from the captioning helper can be returned as successful prompt text.

BLIP is an image-captioning model, as its [model card](https://huggingface.co/Salesforce/blip-image-captioning-large) explains. It cannot promise exact pose, identity, or recovery of the generation instructions.

Fix: call this “Describe reference / Draft prompt,” let the user choose frames, provide editable structured fields, and distinguish observed details from optional creative additions. Return structured error states.

### 21. AI availability and concurrency need stronger handling — medium priority, source finding

`app_local.py:327`, `357`, `402`, `2119`; `ai_prompter.py:33`.

“All installed” ignores the LLaMA dependency even though the UI advertises LLM features. Model loading/inference is not serialized, and unload timers are scheduled from acquisition rather than completion. Concurrent jobs can load duplicate models or contend for GPU/RAM; BLIP globals can change around the timer. Subtitle translation submits the entire SRT into a 4096-token context with at most 1024 output tokens, risking truncation; selecting translation alone does not trigger subtitle generation.

Fix: per-feature readiness (installed/model downloaded/usable), serialized inference or explicit resource limits, reference-counted model lifetimes, cancellation, chunked translation, SRT validation, and preserving the original transcript.

### 22. “100% local” needs qualification — medium priority, source finding

`templates/index.html:9`; `app_local.py:742`, `714`.

The UI loads Tailwind and icons from external CDNs. Song recognition sends extracted audio to Shazam and is enabled by default. Dependency/model downloads and update checks use the network. These are legitimate functions, but the blanket privacy/offline claims obscure them.

Fix: bundle frontend assets, label online actions, make song-recognition network use clear, and provide a genuine offline editing mode. Tailwind calls its [Play CDN development-only](https://v3.tailwindcss.com/docs/installation/play-cdn).

### 23. Updates can leave a half-updated installation — high priority, source finding

`app_local.py:2408`, `2491`, `2515`.

The updater overwrites live application files one by one, without staged validation, rollback, or an archive path-containment check. Dependency installation uses `check=False`. An interrupted extraction or failed installation can still leave a broken combination of code and packages. Archive traversal requires a malicious/compromised update archive; it was not tested against a real release.

Fix: validated release source and archive paths, staged extraction, size limits, dependency checks, a backup/rollback mechanism, and activation on restart after all checks succeed. Block competing update/install operations atomically.

### 24. Builds and startup are not reproducible — medium priority, source finding

`requirements.txt`; `requirements-ai.txt`; `build_staging.py:16`; `app_local.py:714`.

Dependencies have broad minimum versions, and startup runs a daily package upgrade before the server starts. That can delay startup or change behavior without a tested app release; yt-dlp has already been imported when its package is updated. The installer builder hardcodes Python 3.10.11. The downloader explicitly requests Node, but the builder does not bundle or check it, creating a clean-machine risk.

Fix: tested dependency locks and a supported runtime, explicit background engine updates with restart handling, checksums for downloaded build inputs, and startup checks for required external runtimes. Validate the installer in a clean Windows environment. Python identifies 3.10.11 as the [final regular bugfix release of that branch](https://blog.python.org/2023/04/its-time-for-another-set-of-python/); do not treat its age as proof of a particular vulnerability.

### 25. Maintainability and observability need a release baseline

The backend is roughly 2,600 lines and the template more than 3,000 lines, combining UI, workers, AI, filesystem access, and lifecycle operations. No existing automated test suite was found in tracked source. The log SSE endpoint blocks on `q.get()` without heartbeats; long-lived streams use a finite pool of eight web-server threads. Multiple windows and jobs can contend for that pool. Several error handlers swallow useful failures.

Fix: separate media operations, jobs, storage, AI services, and routes; split frontend logic into modules. Add representative fixture-based tests for exported media properties and file safety, a bounded job executor, structured logs, and release smoke checks. A full framework rewrite is not required.

## Most valuable additions for your influencer workflow

These are proposed product features, not claims that a particular paid service is required. Priorities reflect the reference-download and preparation workflow you described.

| Priority | Addition | Practical use | Suggested first version |
|---|---|---|---|
| 1 | Reference collections and tags | Find poses, outfits, locations, lighting, and motion ideas without hunting through folders | Collections, tags, notes, favorites, source URL, creator, import date, and usage/permission notes |
| 1 | Exact-frame picker and contact sheets | Avoid a black first frame or the wrong pose; inspect an entire reference clip quickly | Scrub and frame-step, choose several stills, export a labeled contact sheet, retain timestamps |
| 1 | Visual crop editor | See exactly what will be removed from a photo or video | Draggable crop, anchor point, aspect presets, before/after preview, undo |
| 1 | Saved export recipes | Repeat your common GIF, reference-video, and social-post preparation in one click | Named presets with resolution, codec, duration, size target, and optional captions; verify output properties |
| 2 | Character reference profile | Keep your influencer's recurring appearance and styling organized | Selected reference images, stable character description, wardrobe notes, editable prompt fields; no promise of automatic identity consistency |
| 2 | Project and version history | Connect a reference to prompts, generated variants, and final exports | Immutable originals, edit recipes, parent/child links, side-by-side comparisons, chosen/final labels |
| 2 | Better GIF and short-loop workspace | Make small, smooth loops deliberately | Loop range, preview, fps, palette quality, speed, reverse/boomerang, and measured file size |
| 2 | Editable captions | Correct names and awkward timing before burning text into a video | Transcript editor, timing adjustment, SRT import/export, style presets, and safe-area overlay |
| 2 | Batch organization and duplicate detection | Keep a growing reference library usable | Hash-based duplicates, optional visual similarity, bulk tagging, rename previews, storage totals |
| 3 | Simple photo preparation | Reduce trips to another editor | Rotate/straighten, background removal, transparency, resize, contact sheets and reference-board export |
| 3 | Motion and audio preparation | Make references more useful for generation/editing | Choose motion segments, speed controls, mute/replace audio, fades, loudness adjustment |
| 3 | Lightweight production board | Keep track of ideas through final output | Idea → reference → generated → edited → ready, with notes and reusable caption drafts |

The best first workflow would be: save a reference → tag it → choose the useful frames/segment → combine with your character profile → export using a saved recipe → keep the result linked to the original reference.

## Interface improvements

Make the main actions “Download,” “Prepare,” and “Library,” with advanced AI and metadata controls secondary. Put the preview and relevant settings together. Move the developer console into a collapsible troubleshooting panel; use ordinary progress messages for normal work.

Show dimensions, duration, codec, and file size before processing, then show measured results afterward. Replace “100% detail,” fixed percentage compression claims, and ambiguous master-quality labels with clear quality/size choices.

Add “Edit this file” and “Use as reference” from the gallery, saved last-used folders, real frame stepping, and a preset summary before export. Preserve unfinished selections across tab switches. “Clear Completed” currently empties the whole task container, including active rows (`templates/index.html:628`); it should only remove finished jobs.

Check keyboard access, focus management in modals, readable text sizing, smaller windows, display scaling, and reduced-motion preferences in live UI testing. These are verification recommendations, not confirmed accessibility failures.

## Recommended implementation order

1. **Protect files and the local service:** path validation, HTML injection, safe deletion, unique destinations, verified output replacement, and update rollback.
2. **Make current tools correct:** trim/codec/subtitle separation, crops, animated images, orientation, proper containers, truthful quality settings.
3. **Make jobs dependable:** persistent job state, cancellation, stream buffering, partial-failure reporting, and shutdown handling.
4. **Improve your everyday workflow:** frame picker, visual crop, reference collections, saved export recipes, gallery-to-editor actions.
5. **Add deeper creator features:** character profiles, linked versions, caption editor, and a small production board.

Release checks should cover MP4/HEVC/WebM/MOV, portrait/landscape/square and rotated images, animated GIF/WebP, audio-only and silent videos, non-ASCII filenames, same-name imports, jobs over two minutes, interrupted updates, low disk space, and a clean machine without developer tools. Only add heavier AI integrations after these core paths are dependable.
