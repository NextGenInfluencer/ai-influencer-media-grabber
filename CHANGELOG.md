# Changelog

## [v5.0.12] - 2026-11-04
- Dev `.venv` standardized on Python 3.13 (`run.bat`, `package.json`, `docs/v5-validation.md`, `tests/test_release_regressions.py`):
  - Standardized the PC development virtual environment (`.venv`) on Python `3.13.9` with all core and GPU AI binary wheels installed and verified (`CUDAExecutionProvider`, `audio_separator`, `coverage`), matching the laptop and the Windows installer runtime (`python-3.13.16-embed-amd64`).
  - Updated `run.bat` to prefer Python 3.13 when creating `.venv` and updated `package.json` (`lint:inline`) to invoke `.venv/Scripts/python.exe` before falling back to system `python`.
  - Removed stale `.cpython-310.pyc` bytecode artifacts, updated `.venv/.core-requirements.sha256`, and verified the full 485-test Python suite, `coverage report` (`fail_under = 65`), JS unit tests, `node --check`, and `npm run lint:inline`.

## [v5.0.11] - 2026-11-04
- OTA cleanup of obsolete app files with backup & rollback (`safe_update.py`, `tests/test_updates.py`):
  - Added `_obsolete_files()` during `stage_archive()` to detect existing app files in the install tree that are no longer selected by the incoming release manifest and archive, recording them in `.updates/pending.json` (`removed`).
  - Updated `apply_pending()` to back up every obsolete file to `.updates/backup-<uuid>` and record it in `journal.json` before unlinking it and pruning any resulting empty nested subdirectories inside `ALLOWED_DIRECTORIES`.
  - Updated `rollback()` so failed or interrupted updates restore removed obsolete files alongside modified files from the backup.
  - Enforced strict protection guards (`_is_protected()`, `PROTECTED_NAMES`, `PROTECTED_ROOT_PREFIXES`, `NEVER_UPDATED_PREFIXES`) so user data, `history.json`, cookies, settings, custom fonts (`static/fonts/custom/`, `caption_fonts/`), models, engines, downloads, and projects are never touched.

## [v5.0.10] - 2026-11-04
- Vocal isolation on Python 3.13 with binary wheels (`requirements-ai-gpu.txt`, `requirements-ai-nodeps.txt`, `requirements-ai-common.txt`, `ai_packs.json`, `assets/ai_setup.py`, `ai_core/catalog.json`, `ai_core/asr.py`, `captions.py`, `THIRD_PARTY_NOTICES.md`):
  - Pinned binary-wheel runtime dependencies for `audio-separator==0.48.0` in `requirements-ai-gpu.txt` (`librosa==1.0.0`, `onnx2torch==1.5.15`, `samplerate==0.2.4`, `soundfile==0.14.0`, `scikit-learn==1.9.1`, `soxr==1.1.0`, `resampy==0.4.3`, `julius==0.2.8`, `pydub==0.25.1`, `rotary-embedding-torch==0.6.5`, and Python 3.13 standard-library audio shims) and added `audio-separator==0.48.0` to `requirements-ai-nodeps.txt` (`--only-binary=:all: --no-deps`) so it installs 100% from binary wheels on Python 3.13 without pulling `onnx-weekly` or non-commercial `diffq-fixed`.
  - Added the `audio-separator` item to `ai_packs.json` (`gpu` pack) and `OPTIONAL_MODULES` in `assets/ai_setup.py`, and restored `uvr-kim-vocal-2` (`Kim_Vocal_2.onnx`, MIT) to the `gpu_high` and `gpu_ultra` bundles in `ai_core/catalog.json`.
  - Hardened `ai_core.asr.isolate_vocals()` to expose `imageio_ffmpeg.get_ffmpeg_exe()` on `PATH`, pre-seed local UVR lookup metadata (`download_checks.json`, `vr_model_data.json`, `mdx_model_data.json`) so inference never contacts GitHub offline, and preload CUDA runtime DLLs for `CUDAExecutionProvider`; verified on the 57-line Greek/English song (`08. Ανάσα (Breath) [feat. Airi Oh].wav`) where vocal isolation reduced cue boundary MAE from `0.693s` to `0.616s` (`-11.1%`) and eliminated all collapsed (`< 0.06s`) word timings (`4` → `0`).

## [v5.0.9] - 2026-11-04
- In-app download engine updates & weekly check (`download_support.py`, `app_local.py`, `templates/index.html`, `safe_update.py`):
  - Added `update_download_engines()`, `verify_download_engines()`, `check_download_engines()`, and `weekly_check_due()` (7-day interval persisted in `download_engines.json`), plus `/api/download_engines/status`, `/api/download_engines/check`, and `/api/download_engines/update`.
  - Enforced a strict allow-list (`ALLOWED_ENGINE_PACKAGES = ('yt-dlp', 'gallery-dl')`) and `--no-deps --only-binary :all:` so only `yt-dlp` and `gallery-dl` can ever be updated and no other packages are touched.
  - Verified updates by importing `yt_dlp` and `gallery_dl` in an isolated subprocess, running a dry simulate check (`YoutubeDL({'simulate': True}).prepare_filename(...)` and `gallery_dl.extractor.find(...)`), and running `python -m yt_dlp --version` and `python -m gallery_dl --version`; automatically rolled back to the previous pinned versions (`yt-dlp==<prev>`, `gallery-dl==<prev>`) and re-verified if installation or verification fails.
  - Added the in-app **Update download engines** action (in the Downloader toolbar, More Tools menu, and Software Update modal) displaying package sizes, licenses, current/latest versions, and live update/rollback results.
  - Updated `safe_update._check_dependencies()` so OTA releases may update `yt-dlp` and `gallery-dl` pins in `requirements.txt` while continuing to refuse any other dependency or AI pack changes without the full installer.

## [v5.0.8] - 2026-11-04
- Built-in CPU LLM stability (`ai_core/llm.py`):
  - Reset `llama_cpp.Llama` KV-cache state (`model.reset()`) before each `create_chat_completion` call and set `repeat_penalty=1.15` so consecutive structured-output calls (`translate_lines`) on `qwen3-1.7b` do not loop into phrase repetition and truncate JSON at `max_tokens`.
  - Registered `atexit.register(_unload_builtin)` and guarded `model.close()` so interpreter shutdown never emits `Exception ignored in: <function Llama.__del__>`.
- Whisper audio decoding without system `ffmpeg` (`ai_core/asr.py`):
  - Added `_load_audio()` in `ai_core/asr.py` to decode input audio files to 16 kHz mono `float32` numpy arrays via `imageio_ffmpeg.get_ffmpeg_exe()` before passing to `stable_whisper` / `openai-whisper`, fixing `[WinError 2] The system cannot find the file specified` on laptops without `ffmpeg.exe` on `PATH`.
- Laptop hardware detection & catalog recommendations (`ai_core/hardware.py`, `ai_core/catalog.py`, `ai_core/models.py`):
  - Added Win32 `EnumDisplayDevicesW` fallback (`_display_devices()`) when PowerShell `Get-CimInstance Win32_VideoController` returns empty on Windows laptops, and added `paths.APP_DIR` fallback in `_disk_free_gb()` / `_disk_free()`.
  - Rounded detected system RAM (`round(ram) >= need`) in `catalog.recommended()` so 16 GB laptops reporting `15.9 GB` usable RAM after integrated GPU reservation receive the 16 GB model recommendations (`qwen3-4b`, `whisper-small`).
  - Matched `_item_state('engine-ollama')` in `ai_core/models.py` with `OllamaEngine.status()['installed']` when an external Ollama server is already running.
- Face Swap ETA & per-frame progress (`routes_studio.py`, `ai_core/face.py`, `assets/motion_studio.py`):
  - Added `eta_seconds` (`180` on `laptop`, `60` on `gpu_*`) to `_requirements('face_swap')` and passed `eta_seconds` to `jobs.start('face_swap_video', ...)`.
  - Updated `swap_video()` and `frame_progress()` to emit progress on every frame with live remaining time (`Swapping faces… frame X of Y (~Z s left)`), measuring steady-state per-frame duration from frame 1 completion so cold model initialization does not skew the remaining-time estimate.
- Subprocess termination timeout (`job_process.py`, `ai_core/engines.py`): added a 2-second timeout and `(SubprocessError, OSError)` guard around `taskkill /PID ... /T /F` before calling `process.kill()`.

## [v5.0.7] - 2026-11-04
- Self-sufficient GPU pack & CUDA session verification (`requirements-ai-gpu.txt`, `ai_packs.json`, `assets/ai_setup.py`, `ai_core/face.py`, `assets/motion_studio.py`, `routes_studio.py`):
  - Pinned `onnxruntime-gpu[cuda,cudnn]==1.31.1` in `requirements-ai-gpu.txt` so matching NVIDIA CUDA 13 and cuDNN 9 runtime wheels install directly into the app environment and `onnxruntime.preload_dlls()` loads them without depending on PyTorch or ComfyUI; updated `ai_packs.json` sizes (`onnxruntime-gpu` `approx_mb: 1335`, `gpu` pack `approx_disk_mb: 8300`).
  - Kept `_find_cuda_dll_dir()` ComfyUI fallback strictly as a last resort when neither local `nvidia` wheels nor local compatible `torch/lib` DLLs exist.
  - Verified `session.get_providers()` on `analyzer`, `swapper`, and `restorer` after creating each `InferenceSession`; if `CUDAExecutionProvider` was requested but fell back to CPU, return a visible warning (`"CUDA was requested but is not active (running on CPU – slower)."`) in job status and result payloads instead of silently falling back.
  - Updated `assets/ai_setup.py` `inspect_runtime('gpu')` to instantiate a real `CUDAExecutionProvider` `InferenceSession` and fail if `CUDAExecutionProvider` is not active in `session.get_providers()`.
- Named custom-node patches & `patch_warnings` (`ai_core/engines.py`, `static/ai_setup.js`):
  - Turned every replacement in `ComfyEngine._patch_custom_nodes()` into a named patch in `ComfyEngine._CUSTOM_NODE_PATCHES` returning `'applied_now'`, `'already_applied'`, or `'target_not_found'`; logged warnings and surfaced missing patch targets in `engines.status()['comfy']['patch_warnings']` and the AI Engines sheet.
  - Pinned `ComfyEngine._EXTRA_NODE_PACKAGES` to exact validated versions (`accelerate==1.15.0`, `pytorch-lightning==2.6.6`, `scikit-image==0.26.0`, `soundfile==0.14.0`, `decord==0.6.0`, `onnxruntime-gpu==1.31.1`).
- Non-blocking model storage verification (`ai_core/models.py`, `routes_ai.py`, `static/ai_setup.js`):
  - `ai_core.models.storage()` now returns immediately with `verified: null` (`"Checking…"` in the UI) for unrecorded files and hashes them in a background thread (`_start_background_verify`) or via `POST /api/ai/storage/verify` (`Verify` button in Downloads & Storage).
- Captions Whisper model helper (`captions.py`): replaced the five repeated `try: asr.whisper_model_name() except` blocks with a single `_whisper_name()` helper.
- Third-party notices (`THIRD_PARTY_NOTICES.md`): added `curl-cffi`, `cffi`, `pycparser`, `soundfile`, `decord`, `mediapipe`, `pytorch-lightning`, and `accelerate` with their licenses.

## [v5.0.6] - 2026-11-04
- Creative engine custom nodes (`ai_core/engines.py`, `ai_core/models.py`, `ai_core/catalog.json`):
  - Filtered `_CORE_PACKAGES` (`numpy`, `torch`, `torchvision`, `torchaudio`, `opencv-python`, `mediapipe`, `insightface`, `onnxruntime`, `onnxruntime-gpu`) out of custom-node `requirements.txt` installs so `ComfyUI-LivePortraitKJ`'s `numpy<=1.26.4` pin cannot downgrade NumPy 2 / PyTorch 2.11+cu130; unlinked `.ready` marker if custom-node dependency installation fails.
  - Patched `ComfyUI-LivePortraitKJ` for `mediapipe>=0.10.30` (`vision.FaceLandmarker` fallback when `mp.solutions` / `mediapipe.framework` is absent) and preloaded CUDA/cuDNN DLLs in `landmark_runner.py`.
  - Added `2d106det.onnx` and `comfy_links` to `insightface-buffalo-l` in `ai_core/catalog.json` and patched `ComfyUI-LatentSyncWrapper` (`nodes.py`, `scripts/inference.py`, `latentsync/utils/face_detector.py`, `latentsync/pipelines/lipsync_pipeline.py`, `latentsync/utils/util.py`) for Python 3.13, TorchAudio 2.11, TorchVision 0.29, PyAV `macro_block_size` removal (`write_video_cv2` fallback), and offline local Whisper/InsightFace loading.
  - Set `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` in `ComfyEngine._prepare_home_env()` so custom-node subprocesses printing Unicode banners do not fail under Windows `cp1252`.
- Creative engine lifecycle (`ai_core/engines.py`, `ai_core/comfy.py`): kept the 15-minute `ComfyEngine` idle timer alive while `gpu.status()['comfy']['active']` is non-zero or `ComfyClient.wait()` is polling a running workflow so long video renders (>15 min) are never killed mid-job.
- GPU Face Swap (`ai_core/face.py`): added `_find_cuda_dll_dir(ort)` to locate and preload matching CUDA major-version DLLs (e.g. CUDA 13 `cublasLt64_13.dll` from the Creative engine runtime when `onnxruntime-gpu` targets CUDA 13 while `.venv`'s `torch` ships CUDA 12), accelerating 15 s GFPGAN video face swaps by 10.6× on `CUDAExecutionProvider`.

## [v5.0.5] - 2026-11-03
- Downloader (`requirements.txt`): added `curl-cffi==0.16.3`, `cffi==2.1.1` and `pycparser==3.12` so `yt-dlp` has native Chrome TLS impersonation for TikTok and X extraction.
- Downloader UI (`templates/index.html`): clear cached `processedUrls` when a URL preview fails, when the login session (`#browser`) changes, or when the download form is submitted so re-previewing after importing cookies or switching to Firefox works immediately.

## [v5.0.4] - 2026-11-03
- Translation routing (`ai_core/translate.py`): expanded `STOPWORDS['en']` with core English words (`a`, `an`, `no`, `not`, `by`, `into`, `about`, `where`, `when`, `who`, `how`, `why`, `out`, `up`, `down`, `back`, `through`, `like`, `from`, `at`, `as`, `but`, `or`, `if`, `never`, `always`, `nothing`, `nobody`, `somebody`, `everything`) and broke Latin stopword ties in favor of `target_code` so English lyric lines containing `'a'` or `'no'` are not misclassified as Portuguese/Spanish.
- Captions translation (`captions.py`): restricted chorus pre-seeding in `translate_project` to lines outside `pending_ids` so re-translating unlocked already-approved lines calls `ai_translate.translate_lines` instead of returning cached chorus text.
- Captions Translation Review modal (`static/captions.js`): display each line's translation route (`Translator`, `Helper (mixed language)`, or `Same as original`) in `showTranslationReview()`.
- Captions transcription & alignment status (`captions.py`): display the active Whisper model (`Whisper <model>`) in `/transcribe` and `/align` running and completion status messages.

## [v5.0.3] - 2026-11-03
- Downloads & Storage: `ai_core.models.storage()` now verifies pre-existing installed model files against their catalog SHA-256 and records them in `.verified.json` so existing models (FLUX.1 schnell, Wan 2.1 I2V 14B, InSwapper 128, InsightFace buffalo_l, Whisper base, Qwen3 4B) display as `Verified` instead of `Not verified`.
- AI Engine Pack notice: avoided repeating "NVIDIA NVIDIA ..." in the recommendation reason when the GPU name reported by `nvidia-smi` already starts with `NVIDIA`.

## [v5.0.2] - 2026-11-03
- Hardware detection: added standard-library OS RAM fallback (`GlobalMemoryStatusEx` on Windows, `sysconf` on POSIX) when `psutil` is not installed (Essentials / core environment), and fixed `HardwareProfileTests` so tests do not require `psutil` in base environments.
- Model & engine installer: use `storage_utils.replace_with_retry` when swapping downloaded files, extracted engine directories and `.verified.json` into place on Windows to tolerate transient antivirus/indexer file locks (`[WinError 5] Access is denied`).
- AI Cleaner: fixed a `NameError` (`time` not imported) in `cleaner.clean_photo` when retrying a transient Windows file-replace lock, and unified photo/video atomic replacement on `storage_utils.replace_with_retry`.

## [v5.0.1] - 2026-11-03
- AI Setup: fixed stray "null" text next to model names in the checklist.
- AI Setup: the vocal isolation model is no longer pre-selected in profile bundles until its runtime library ships in an AI pack (it stays installable from the catalog).

## [v5.0.0] - 2026-11-03

**Full installer required** (AI dependencies changed). User media, history, characters, caption projects and credentials are preserved; caption projects get a `pre-v5-project.json` backup before the one-time translation repair.

### Honesty & public-release readiness
- Removed every fabricated AI output: OpenCV-gradient "FLUX keyframes", zoompan "Wan 2.1" videos, keyword "AI Director", Copilot placeholder translations/options/templates, hardcoded "Wan Ready" badges and other false labels. Missing capabilities now show "Not available on this PC" with requirements and a Set up AI action (HTTP 424 + `setup_hint`).
- No silent downloads: Whisper, BLIP, Llama and InsightFace auto-downloads replaced by a consent flow. Every item shows live size, source, license (non-commercial items require explicit acceptance), RAM/VRAM and Local/Cloud before installing; downloads are pinned and SHA-256 verified.
- New AI Setup wizard (hardware-detected profiles: Essentials, Laptop/CPU, GPU 6–10 GB, GPU 12–16 GB, GPU 24 GB+), AI Engines sheet (Ollama / Built-in / Creative engine, model roles, cloud keys) and Downloads & Storage center with one-click reclaim of duplicates/obsolete models.
- `THIRD_PARTY_NOTICES.md`, `docs/PRIVACY.md`, `docs/RESPONSIBLE_USE.md`; first-use download/copyright and responsible-use (face swap, lip-sync) notices.

### Local AI
- New `ai_core` package: hardware profiles, pinned model catalog, consent-gated verified installs, VRAM broker (one heavy model at a time), app-managed Ollama and ComfyUI engines, one role router (helper, translator, vision, speech) over Ollama (GPU) or the built-in llama.cpp engine (laptops).
- Speech: profile-chosen Whisper (large-v3-turbo on 12 GB GPUs) with VAD, no context carry-over and language detection on the most-voiced window.
- Translation routing: lines already in the target language are kept, single-language lines use the Translator model (TranslateGemma when installed), mixed-language lines use the Helper; A/B compare per line. Lyrics are never sent to the cloud.
- Vision: structured scene descriptions feed the Kling/Nano prompt builder (BLIP-large removed).
- Face swap on GPU (CUDA) / DirectML / CPU with GFPGAN restoration, identity tracking, no frame cap and original resolution.
- AI Studio: real FLUX keyframes/edits, Wan 2.2 5B / Wan 2.1 14B animation, LatentSync lip-sync and LivePortrait via ComfyUI; opt-in cloud Kling motion-control, LivePortrait and Nano Banana with cost confirmation; async jobs with progress and cancel.
- Copilot: streaming agent with real tools, proposals with diff/ETA before applying, full caption context, honest errors.

### Captions Studio
- Fixed translations disappearing after editing (inline editor stored raw text instead of the source hash; server marked them stale and hid them). Single translation writer, whitespace-normalized hashes, visible "Needs review" state with Keep/Retranslate, export guard, and automatic recovery of affected projects.
- Per-script karaoke retry for mixed Greek/Latin/Hangul lines; lyric proposals keep line identity and translations.
- Shared animation constants for preview/export, glow halo layer, title/box parity, single visualizer, storyboard bridge fix, render pruning, input-seeking check renders, progress, per-project Stop.

### Downloader
- Instagram: fixed fake "complete" on empty profile downloads, profile listing via gallery-dl, post vs profile detection, reels with audio, byte-exact photos, single extraction per post, fail-fast login message.
- Cookies: platform-aware options (Windows: Anonymous, Firefox, Import cookies.txt; Chrome/Edge removed on Windows due to App-Bound Encryption), cookies.txt import/status/delete stored in user data.
- Fixed Retry button, playlist URLs, cross-drive subtitle burn-in, first-frame failures, history corruption recovery, capped gallery scans.

### Platform
- Hardware-chosen CPU / DirectML / GPU AI packs with an itemized consent notice; staged OTA release manifest; shared atomic JSON writes with Windows retry; CI with coverage, ESLint on inline scripts and all JS checks; waitress 24 threads.

## [v4.2.3] - 2026-11-02
- Copilot conversational subtitle and translation editor, app knowledge base, reading-speed audit and app controller.

## [v4.2.2] - 2026-11-02
- Updater: safe Windows subprocess restart with spaces in path and active health-check polling.

## [v4.2.1] - 2026-11-02
- AI Studio engine detection and model hub changes (superseded by v5.0.0).

## [v4.2.0] - 2026-11-01
- Instagram profile downloader, AI Studio gallery tab and Motion Studio integration.

## [v4.1.1] - 2026-11-01

- **Native Instagram Carousel & Photo Downloader**: Added direct native extraction for Instagram multi-item carousels, photo posts, and mixed photo/video posts. Bypasses anonymous access restrictions, downloading all high-resolution original images and video slides without login failures.
- **Instagram Preview Support**: Added resilient fallback in `/api/preview` to extract creators, titles, and thumbnails for Instagram posts and carousels, avoiding preview errors.
- **Gallery Downloader Cleanup**: Prevent orphaned empty `Gallery-*` temporary directories from remaining on disk on failed gallery downloads.
- **Updated Download Dependencies**: Upgraded `yt-dlp` and `gallery-dl` to latest stable versions.

## [v4.1.0] - 2026-10-31

- **AI Influencer Studio Suite & Local Copilot**: Added in-app conversational and action-driven AI Copilot (Ctrl+K) with hardware-adaptive routing (NVIDIA RTX 3080 Ollama qwen2.5:14b / llama3.1:8b GPU acceleration with automatic CPU fallback). Supports direct tool execution for caption presets, timing offsets, viral social media posts, and prompt generation.
- **Universal Character Profile Library**: Added persona manager supporting @Airi and custom creator identities with face portrait and 3-view turnaround triptych references, aspect ratio toggles, and natural-language prompt formatting for Google Flow Nano Banana 2.1 / Pro.
- **1-Click Reference Frame Snapper**: Added high-resolution PNG snapshot tool (Grab Frame / hotkey S) directly on active video preview players in Captions Studio and Downloader, saving pristine frames to Documents/Media Grabber/References with instant clipboard copy and persona assignment.
- **AI Song Storyboard**: Added automated scene segmentation and Google Flow Nano Banana prompt generator with dynamic lyric-aware visual atmosphere detection, 1-click prompt copying, and reference frame snapping synchronized to song timing.
- **Motion Studio & Timeline Background Integration**: Added character motion interface allowing creators to composite character portraits with lip-sync recordings or driving videos with driving audio, and set the result directly onto the multitrack timeline with full project persistence.
- **Enhanced Bilingual Lyric & Translation Editing UX**: Made translation subtitle editing directly visible and accessible on cue cards and selection editor with active line badge, glowing focus cues, and live sync across video stage and export formats.
- **System Stability & Safe Updates**: Included copilot.py and characters.py in atomic updater manifest (safe_update.py) and added comprehensive route, security, and regression tests passing 100% across all suites.

## [v3.2.1] - 2026-10-30

- Verify Ollama model metadata before sending lyrics; reject remote/cloud aliases and unverifiable models, and refuse redirects. Filter remote entries from the model picker.
- Flag same-line Korean/Greek lyrics for timing review even when they contain no English.
- Clarify historical installer evidence and publication status in the completion record.

## [v3.2.0] - 2026-10-30

- Add separate reviewed/locked translation tracks, contextual local translation proposals, repeated-line reuse, resumable translation and bilingual export controls.
- Add shared caption layout controls, per-line styles and editable word timing blocks.
- Isolate pending upload drafts, emoji/sticker removal state, stock notices, and unsaved lyric text drafts between projects and preserve them when reopening settings, switching projects, or reloading.
- Continue exported entrance animations across karaoke word boundaries; use existing word timings in typewriter mode even without highlighting.
- Fit long words and unspaced phrases inside shared caption layouts without changing karaoke tokens; share the fitted size and spacing between preview and export.
- Animate rounded caption backgrounds alongside their text; combine word-pop with entrance scaling and retain padding during slide previews.
- Resolve missing Greek/Korean glyphs to bundled fallback fonts (Roboto / Noto Sans KR) for shared layout, preview and export, and prevent decorative Latin/CJK fonts with isolated Greek math symbols (μ, π, Δ, Ω) from splitting Greek words mid-word.
- Automatically flag abnormally stretched word timings (> 4.0s across sustained notes or instrumental gaps) and same-line mixed-script lyrics (state: 'review') during forced alignment so they are surfaced for listening review.
- Include `assets/*.py` helper modules in /api/health restart detection and support isolated staging/output paths (MEDIA_GRABBER_STAGING_DIR / MEDIA_GRABBER_OUTPUT_DIR) in `build_staging.py` and installer.iss.
- Add local translator setup with a pinned official Qwen download, checksum verification, progress, cancellation cleanup, disk-space checks and AI Engine prerequisite guidance.
- Verify AI library imports in a fresh process before either installer reports success; handle broken native libraries in AI status checks and require a prebuilt llama runtime instead of compiling it on users' machines.
- Constrain optional AI package installation to the core dependency lock, protecting shared packages used by downloading and song identification.
- Preserve composition settings/uploads after failed renders and retire consumed drafts only after success; sequence-only renders retain unrelated pending edits.
- This dependency-changing version requires the full installer when upgrading from the published release; source-only OTA staging correctly refuses it.
- Stream optional Ollama translations with cancellation checks and response limits; reject interrupted or malformed results while retaining saved lyrics.
- Prepare build tools explicitly for embedded Python and install the AI Pack without a separate build environment, fixing stable-ts setup failures. Verify the actual BLIP and alignment interfaces before reporting AI readiness.
- See the [lyrics workflow guide](docs/creator-lyrics-guide.md) and [completion plan](docs/creator-completion-plan.md) for current behavior and verification boundaries.

## v3.1.5 — Reviewable, resumable lyric syncing
- Correct lyrics and Sync lyrics now prepare a reviewable proposal in the editor. Compare current/proposed text, listen to a line, apply all, keep current captions, or review later.
- Saved captions stay unchanged until Apply; stale proposals cannot overwrite later caption edits. Applying retains a restore point.
- Sync checkpoints its first successful whole-range alignment, then refines bounded lyric sections from those anchors. Resume skips completed sections with the same text, range, language and project.
- Failed refinements retain first-pass timing and are marked for listening review. This does not guarantee real-song alignment accuracy; mixed-language first-pass alignment still needs matching language sections.


All notable changes to the AI Influencer Media Grabber project will be documented in this file.

## [v3.1.4] - 2026-10-27

### Reliability and project safety
- Isolate application storage before test discovery; tests no longer initialize against real history or projects.
- Share the installer/OTA payload list, include the encoder dependency, and support the older updater's asset allowlist.
- Back up project metadata before its first save in this version. Keep original media unchanged.
- Store custom fonts in user data, preserve legacy uploads, prevent filename/family replacement, and exclude uploads from release packages.

### Editor and rendering
- Preserve source positions when splitting clips, including repeated sequences; apply speed to single-clip sequences.
- Add source-start editing, sequence Undo/Redo, and a notice that prevents exporting unapplied sequence edits.
- Detect audio per source and pad silent/short segments independently.
- Normalize transition inputs and preserve timeline duration; exercise every supported transition with real renders.
- Compose final song-video exports from original assets in one pass, including the selected output frame rate and canvas size.
- Separate live stickers from prepared previews; export pop, fade, slide, and static stickers consistently.
- Reveal individual characters in karaoke typewriter exports.
- Add a CPU export override and one CPU retry for recognized hardware-encoder failures.
- Replace misleading quality labels with explicit output/upscaling descriptions.

### Lyrics
- Resume interrupted per-line karaoke timing from a separate checkpoint, without applying partial changes to saved captions. Retry only uncertain lines.
- Preserve alignment confidence flags and actual word boundaries instead of stretching words to caption edges.
- Preserve existing word timings when a supplied line is unchanged.
- Correct or align a selected range without deleting captions outside it; reject boundaries that split existing lines.
- Clarify the difference between correcting text with existing timing and aligning lyrics to audio.

### Verification
- Added real render, updater compatibility, font safety, lyric preservation, and GPU fallback regression coverage.
- Full language/audio accuracy and broader editing improvements remain separate verification work; see docs/stability-roadmap.md.

## [v3.1.3] - 2026-10-23

### Added & Improved
- **Creator Video Studio Responsive Stage Scaling**:
  - Replaced legacy fixed height constraints with dynamic viewport sizing that monitors `.capcutCenter` via `ResizeObserver`.
  - Preview stage now automatically scales up to 100% of available screen space in fullscreen and windowed modes while strictly preserving the video's aspect ratio (16:9 horizontal, 9:16 vertical reels/TikTok, 1:1 square).
- **Overhauled Clip Sequence Cards (Zero Horizontal Overflow)**:
  - Redesigned sequence list items into structured 2-row cards eliminating horizontal scrollbars:
    - Row 1: Clip index badge (`#1`), truncated file name, reorder buttons (`◀` `▶`), and an always-visible red-accented delete button (`✕`).
    - Row 2: Duration input with unit label (`⏱ [0] s`) and speed selection dropdown (`⚡ [1× Normal ▼]`).
  - Organized drawer action buttons into clean 2-column macOS grids (`🌐 Free Stock` / `➕ Upload Clips`, `✂️ Split Playhead` / `⚡ Cut to Beat`, `Split evenly` / `10s each`).
- **4 New Viral 1-Click Caption Presets**:
  - **⚡ Beast Pop**: High-contrast bold yellow font (`#ffe600`), thick black outline, and dynamic spring pop entrance.
  - **🌆 Cyberpunk**: Vibrant neon cyan (`#00f0ff`) with magenta highlight (`#ff0055`), glowing aura, and typewriter reveal.
  - **☕ Frosted Vlog**: Elegant modern vlog subtitle featuring ivory typography over a soft frosted translucent pill backdrop.
  - **🌅 Sunset Glow**: Warm coral (`#ff7b54`) to golden karaoke highlight with smooth spring slide-up animation.
- **Apple macOS Aero Design Refinement**:
  - Upgraded Creator Studio controls, dropdowns, and buttons to Apple macOS Pro standards with frosted acrylic glass surfaces, SF Pro typography, and crisp border highlights.

## [v3.1.2] - 2026-10-22

### Fixed
- **Permanent Fix for Desktop Auto-Shutdown / Spontaneous Closing**:
  - Completely disabled the self-terminating heartbeat watchdog by default so the desktop app runs continuously without unexpected closures after periods of inactivity, window minimization, or Chromium background timer throttling.
  - Watchdog is now strictly opt-in via `--enable-watchdog` or `MEDIA_GRABBER_ENABLE_WATCHDOG=1` with a safe 24-hour timeout (86,400s), ensuring everyday desktop users experience zero random shutdowns.

## [v3.1.1] - 2026-10-22

### Added & Fixed
- **Dynamic Lyric Animations & Instant Live Preview**:
  - Fixed an issue where changing subtitle animations (*Typewriter*, *Pop Entrance*, *Smooth Fade*, *Slide Up*, *Zoom In*) while paused showed no visual feedback because entrance timers only evaluated during playback.
  - Selecting any animation now immediately triggers a fluid 60fps live preview on the active stage canvas, even when paused.
  - Added a dedicated 1-click `▶ Preview` action button next to the Animation dropdown in Creator Studio to replay and preview animations on demand.
  - Fixed `Typewriter` animation bypass when word timings (*Karaoke*, *Cumulative*, *Word Pop*) were active: future words are hidden until reached, the active word types character-by-character with an authentic blinking cursor (`▎`), and karaoke highlights/pops trigger dynamically.
  - Upgraded entrance motions to natural Apple macOS Pro spring easing curves with satisfying scale overshoot.
  - Updated ASS video subtitle export engine in `captions.py` so rendered MP4s display the exact progressive typewriter motions.

## [v3.1.0] - 2026-10-22

### Fixed & Improved
- **Watchdog & Keepalive Resilience (No Unexpected Shutdowns)**:
  - Fixed an issue where the background Python server terminated unexpectedly when minimized, backgrounded, or idle due to aggressive 18-second watchdog timeout and Chromium timer throttling.
  - Increased watchdog idle tolerance to 300 seconds (5 minutes) and added `--no-watchdog` CLI / `MEDIA_GRABBER_NO_WATCHDOG=1` environment override support.
  - Implemented reactive `visibilitychange` and `focus` keepalive event listeners across all pages (`index.html` and `captions.js`) to immediately reconnect sessions when refocusing the app.
  - Removed fragile 4-second shutdown trigger on page navigation (`beforeunload` / `pagehide`), ensuring seamless transitions between Creator Studio and Downloader without connection drops.

## [v3.0.0] - 2026-10-22

### Added & Improved
- **GPU Hardware Acceleration Engine (`hwaccel.py`)**:
  - Automatic micro-encode hardware detection probing NVIDIA NVENC (`h264_nvenc`, `hevc_nvenc`), Intel QuickSync (`h264_qsv`, `hevc_qsv`), AMD AMF (`h264_amf`, `hevc_amf`), and Apple VideoToolbox.
  - Seamless, zero-configuration software CPU fallback (`libx264` / `libx265`).
  - Up to 4×-8× faster video encoding across Media Tools, Creator Studio composition exports, face tracking, and subtitling.
  - Exposes dedicated `/api/hwaccel` telemetry endpoint and header badge indicator.
- **Apple macOS Pro Acrylic Sheet Dialogs**:
  - Full modernization of secondary modals (`browserModal`, `mediaPreviewModal`, `aiInstallModal`, `appUpdateModal`) with frosted glass depth (`backdrop-blur-2xl` to `backdrop-blur-3xl`), obsidian translucent cards, and Apple System Blue `#0071e3` tactile action buttons.
  - Eliminated legacy high-contrast pink inline styles from modal components.
- **Activity Hub Direct Actions**:
  - Completed queue cards now offer instant 1-click action pills: `📂 Folder` (reveals in Explorer), `▶ Play` (launches local media player), and `📋 Copy Path` (copies absolute file path).
  - Failed downloads provide an instant `↻ Retry` action button to re-queue tasks seamlessly.
- **Timeline Pro Precision Trimming & Storyboard Controls**:
  - Drag-to-trim edge handles (`||`) on caption cue blocks with Apple Blue hover highlights and tactile cursor feedback.
  - Storyboard clip sequence reordering with clean `◀` and `▶` pro arrow controls.
- **Streamlined Top Bar Navigation**:
  - Cleaned primary segmented navigation bar; moved secondary utilities (Kling Prep, Carousel Studio) into an elegant overflow dropdown menu.
- **Comprehensive Test Coverage & Stability**:
  - Added `tests/test_hwaccel.py` verifying detection logic, CPU fallback, preset arguments, and API endpoint behavior (110/110 tests passing).
  - **Watchdog & Keepalive Resilience**: Eliminated aggressive 18-second auto-shutdown watchdog that killed the app when minimized or backgrounded; increased idle tolerance to 300 seconds (5 minutes), added `visibilitychange` and `focus` instant keepalive reconnects, and removed hair-trigger 4-second shutdown on page navigation.

## [v2.8.1] - 2026-10-22

### Added & Improved
- **Apple macOS Pro UI / UX Overhaul & Effortless Workflows**:
  - **📋 1-Click Clipboard Paste & Clear**: Added instant "📋 Paste URL" button that grabs clipboard text and adds it to the download queue, plus a dynamic "✕ Clear" button.
  - **✨ Reactive Platform Detection Badges**: Live badges for TikTok, Instagram Reels, YouTube, X / Twitter, Pinterest, and Vimeo that illuminate with signature brand glows when links are pasted.
  - **📂 1-Click File Explorer Access**: Added direct "📂 Open" buttons adjacent to Save Folder and Cleaner inputs to immediately reveal files in Windows Explorer.
  - **Modern Apple Frosted Empty States**: Replaced raw unstyled text in Gallery and Download History with frosted acrylic cards containing iconography, friendly guidance, and 1-click CTA buttons ("Start a Download", "Open Folder", "View All Media").
  - **⌨️ Creator Studio Keyboard Shortcuts Modal & Navigation**: Added a "⌨️ Shortcuts" quick-reference modal, frame-by-frame stepping (`←/→` 0.1s / Shift 1.0s), quick line deletion (`Delete` / `Backspace`), and line loop toggle (`L`).
  - **🔍 Timeline Zoom Controls**: Added 1-click Zoom In (`+`), Zoom Out (`−`), and `Fit` buttons for instant timeline overview.
  - **Stage Canvas Ready Badge**: Polished empty video preview stage with an acrylic movie canvas badge.

## [v2.8.0] - 2026-10-22

### Added & Improved
- **TikTok & Snapchat Signature Aesthetic Filters (1-Click Presets & 0ms Live Preview)**:
  - Added viral social media aesthetic color grading and visual styling presets with instant CSS live stage preview and native FFmpeg export filters:
    - **✨ TikTok Beauty Glow** (`beauty`): Iconic 'Smooth Cam' skin softening, delicate highlight bloom, and luminous porcelain skin tone.
    - **📼 VHS 90s Camcorder** (`vhs`): Authentic vintage home-video look with magnetic chromatic aberration, retro analog tape noise, and scanline depth.
    - **🌅 Teal & Orange Cinematic** (`teal_orange`): High-fashion travel influencer color grade with deep teal shadows and warm sunset skin tones.
    - **💖 Vaporwave Neon** (`vaporwave`): Cyberpunk magenta and electric cyan anime aesthetic with high-saturation pop.
    - **💎 KiraKira / Bling Sparkle** (`bling`): Specular highlight boost and starburst glitz pop.
    - **🐟 Fish-Eye Lens** (`fisheye`): Convex wide-angle bubble lens distortion for skate videos, meme POVs, and dynamic camera angles.
    - **🎞️ Film Noir / Gotham Dark** (`noir`): High-contrast crushed blacks, desaturated silver tones, and moody TikTok noir aesthetic.
- **OpenCV Face Snapping for Stickers & Props (🎯 Snap to Face)**:
  - Added local computer vision face detection using OpenCV (`haarcascade_frontalface_default.xml` & `haarcascade_eye.xml`) with zero cloud dependencies or external API subscriptions.
  - Added **'🎯 Snap to Face (this frame)'** in the Stickers pane: finds the subject's face at the playhead and snaps the sticker to that position (single frame coordinate grab).
  - Three smart snapping targets:
    - 👑 Head / Crown: Positions stickers floating above the head (ideal for crowns, halos, dog/cat ears).
    - 🕶️ Eyes / Shades: Aligns glasses/sunglasses across eye level.
    - 🎭 Face Center: Centers props and masks directly over the facial midpoint.
  - True-color emoji stickers powered by Segoe UI Emoji with proper alpha transparency.
- **Sub-Millisecond Float Precision Sanitization & Auto-Clamping**:
  - Resolved `ValueError: Value must be between ...` caused by floating-point rounding drift when dividing audio ranges during lyric synchronization.
  - `validate_edit` absorbs edge drift (tolerance 0.01s), ensuring lyrics and word timings remain resilient during alignment and auto-estimation while preserving validation integrity.
- **Unified Preview & Export Geometry**:
  - Synchronized sticker coordinate math between the web stage preview and FFmpeg filtergraph using center-anchored bounding boxes.
- **Apple macOS Modern Pro Visual Design**:
  - Upgraded both the Main Dashboard and the Caption Studio to an Apple-inspired Pro design language.
  - Native SF Pro typography stack (`-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display"`), frosted glass acrylic materials (`backdrop-filter: blur(28px) saturate(190%)`), hairline border highlights, and Apple System Blue primary action buttons.
  - Segmented control navigation pills with smooth active indicator physics, refined Apple custom range sliders, and macOS-style sheet dialogs.

## [v2.7.2] - 2026-10-21

### Added & Improved
- **Cut-to-the-Beat / Auto Beat-Drop Snapping (`⚡ Cut to Beat`)**:
  - Added 1-click `⚡ Cut to Beat` button in the sequence storyboard bar.
  - Automatically analyzes the song's audio peaks and beat transients (`CaptionTiming.detectBeats`), snapping all clip cut points to the nearest musical beat drops for effortless rhythmic TikTok/Reels-style music video editing.
- **Per-Clip Speed Ramping & Slow-Mo (0.25× to 4×)**:
  - Added dedicated speed multiplier dropdown (`0.25× Slow`, `0.5× Slow`, `0.75×`, `1× Normal`, `1.25×`, `1.5×`, `2× Fast`, `4× Hyper`) on every clip pill in the sequence storyboard.
  - Configures per-segment video presentation timestamps (`setpts=PTS/{speed}`) and audio speed filters (`atempo={speed}`), maintaining bit-exact audio synchronization and slow-mo video fluidity.
- **Stickers, Emojis & Transparent Graphic Overlay Track**:
  - Added a dedicated **Stickers** dock tab and pane (`data-dock-pane="stickers"`).
  - 1-click viral reaction emojis (`🔥`, `💃`, `👑`, `✨`, `💯`, `💖`, `⚡`, `🎧`, `🚀`, `🪩`, `⭐`, `🎉`) rendered as high-res transparent PNG stickers with automatic Pillow typography.
  - Direct upload support for custom transparent PNG, animated GIF, and WebP graphics.
  - Precise timing & placement controls: start time, duration, X/Y screen position, size scale, opacity, fade in/out, and motion entrance animations (`pop` bounce, `fade`, `slide`).
  - Real-time video player stage preview via `#stageSticker` and multitrack timeline visualization on `#videoTrackLane`.

## [v2.7.1] - 2026-10-21

### Added & Improved
- **Split Clip at Playhead (`Ctrl+B` / Split Clip Button)**:
  - Added 1-click `✂️ Split Clip` button in the center playback controls, `✂️ Split at Playhead` in the storyboard sequence bar, and universal `Ctrl+B` / `Cmd+B` keyboard shortcut.
  - Automatically splits the active video or photo clip in the sequence at the current playhead position (`video.currentTime`) into two adjacent segments with exact millisecond precision.
  - Automatically freezes relative auto-split durations so surrounding clip timings and lyrics alignment remain 100% stable.
- **Custom Font Upload / User Font Import (`.ttf` / `.otf`)**:
  - Direct font drag-and-drop / file upload (`POST /api/captions/fonts/upload`) supporting any TrueType or OpenType font up to 25MB.
  - Strict security validation: verified TrueType/OpenType magic headers (`\x00\x01\x00\x00`, `OTTO`, `true`, `typ1`, `ttcf`), Pillow parsing, and font table metadata extraction.
  - Instant live typography: dynamically injects `@font-face` rules for 0ms web canvas preview without page reloads.
  - Bit-exact ASS/libass export: custom fonts are automatically copied to temporary `caption_fonts/` during rendering so FFmpeg renders custom typography without requiring OS-level administrator font installation.
- **Advanced Export Quality & Framerate Presets**:
  - Added **Smooth 1080p 60fps** (`60fps`: CRF 17, 320k audio, 60fps framerate) for ultra-fluid dance and social media reels.
  - Added **4K Ultra HD 2160p** (`4k`: CRF 15 studio master, 320k audio, 2160p scaling) for vertical 2160×3840 and horizontal 3840×2160 exports.
  - Integrated into the finish bar (`#renderQuality`) and validated in backend pipeline.
- **Timeline Audio Indicators**:
  - Visual audio badge (`🔊` / `🔇`) rendered directly on sequence clip blocks in the bottom timeline (`#videoTrackLane`).
  - Displays instant visual feedback whether each clip has active audio or is muted/silent.

## [v2.7.0] - 2026-10-21

### Added & Improved
- **CapCut-Style Video Transitions Between Multi-Clip Cuts**:
  - Seamlessly transition between cuts in multi-clip video sequences with 9 transitions: `Dissolve / Crossfade` (`fade`), `Fade to Black` (`fadeblack`), `Flash White` (`fadewhite`), `Slide Left` (`slideleft`), `Slide Right` (`slideright`), `Zoom / Circle Crop` (`circlecrop`), `Wipe Left` (`wipeleft`), `Wipe Right` (`wiperight`).
  - Configurable transition durations from 0.1s to 2.0s with frame-accurate FFmpeg `xfade` chaining and color-dip blending.
- **100% Non-Destructive Reversible Video Filters & Visual FX**:
  - Composition generation and editing now preserves raw pristine pixels (`bake_fx=False`).
  - Switching filters (e.g. `Vintage`, `Cyberpunk`, `Warm`, `Noir`) or returning to `None` immediately restores untouched original colors without double-baking or pixel degradation.
  - GPU-accelerated 0ms CSS preview in the browser and dynamic single-pass FFmpeg application during export.
- **Multi-Clip Background Audio Mixing with Silence Fallback**:
  - Background audio tracks from video clips in multi-clip sequences are mixed under the main song with adjustable volume and audio ducking.
  - Generates synchronized stereo silence (`anullsrc=r=44100:cl=stereo`) for still photos or muted clips so mixed sequences never desynchronize.
- **Animated Caption & Title Card Motion Presets**:
  - Added `Zoom In` (smooth scale-in entrance) and `Typewriter` (progressive character-by-character typewriter reveal) animations.
  - Implemented both in the interactive player stage (`drawCaption`) and in exported ASS subtitles.

## [v2.6.1] - 2026-10-21

- Fixed the social clip grabber's missing `cast` failure. Downloads now run in a cancellable worker with a three-minute deadline, file-size/duration limits, live-stream filtering, isolated temporary files and active-job tracking.
- Restricted clip URLs to HTTPS YouTube, TikTok and Instagram hosts without credentials or custom ports; disabled unrelated/generic extractors for this workflow.
- The isolated Python download worker rejects private/reserved socket destinations, including redirected and DNS-resolved targets.
- Added a cancellable, time-limited YouTube search worker and respected the requested duration limit.
- Fixed long-song cycling silently stopping after 20 repeats/60 cuts. Repeated clips share decoder inputs; sequences above 600 cuts now show an explicit error.
- Added route-level download/cancellation tests and a real FFmpeg repeated portrait/landscape regression check.
- Remaining audit items (reversible effects, clip audio and stock metadata) are not included in this stability release.

## [v2.6.0] - 2026-10-21

### Added & Improved
- **CapCut-Style 4-Zone Desktop Studio (`/captions`)**:
  - Redesigned the Captions & Lyrics editor into a full-viewport 4-zone workspace with a Left Icon Dock (`🎬 Media & Clips`, `🌐 Free Videos`, `📝 Lyrics & AI`, `✨ Filters & FX`, `🎵 Audio & Voice`, `🎞️ Canvas & PiP`), Center Video Player Stage, Right Inspector (`⚡ All`, `💬 Lines & Words`, `🎨 Text Style`), and Bottom Multitrack Timeline (`🎬 Clips`, `🎵 Audio`, `💬 Lyrics`) with zero blocking modal popups.
- **Multi-Clip Video Sequence Storyboard**:
  - Stitch up to **30 video or photo clips** into a sequence (`settings.sequence`), reorder clips (`←`/`→`), set per-clip durations (`0s` Auto split song evenly or custom seconds like `10s` to cycle clips across the song), preview every clip block on `#videoTrackLane`, and render stitched multi-clip sequences via FFmpeg `concat`.
- **Free Video Search Without API Keys (Mixkit HD Stock & YouTube Shorts / Google) + Social Clip Grabber**:
  - **🔥 Mixkit HD Stock (`mixkit`)**: Built-in zero-key search for 1,370+ free HD watermark-free dance & aesthetic stock videos.
  - **📱 YouTube Shorts / Google (`youtube`)**: Built-in zero-key vertical video search via `yt-dlp`.
  - **🔗 Direct TikTok / Instagram Reel / YouTube Short Clip Grabber (`POST /api/captions/stock/grab-url`)**: Paste any TikTok dance video, Instagram Reel, or YouTube Short URL directly inside the studio to download without watermark and append to your music video sequence (replacing the clip's audio with your song).
  - **1-Click Dance & Vibe Category Chips**: Instant category buttons (`💃 Dance`, `🔥 Street / Hip-Hop`, `🪩 Club & Party`, `💃 Modern Dance`, `✨ Neon Aesthetic`, `🌆 Night Drive`, `🎤 Concert / DJ`, `🌊 Sunset Vibe`).
- **CapCut-Style Video Filters, Visual FX & Audio FX Suite**:
  - **Video Filters**: `B&W`, `Sepia`, `Vintage Film`, `Cyberpunk Neon`, `Warm Golden Hour`, `Cool Cinema`, `High-Contrast Dramatic`, and `Dreamy Glow` with live browser preview and FFmpeg export.
  - **Visual FX**: Cinematic Vignette, Film Grain, Sharpen, and RGB Chromatic Glitch.
  - **Audio Cleanup & Effects**: FFT Noise Cancellation (`afftdn`), Voice Isolation & Speech Clarity, `Echo`, `Concert Hall Reverb`, `Studio Vocal`, `Lo-Fi Radio`, `Bass Boost`, and `Chorus` in both `/captions` and the Media Tools converter (`/`).
- **Multilingual Karaoke, Audio-Reactive Visualizers, Carousel Studio & Kling Contact Sheets**:
  - 14-language + mixed-language (`en-fr`, `en-ko`, `en-fr-ko`) batch karaoke alignment with Needleman-Wunsch lyric correction, bundled Google Fonts (`Montserrat`, `Roboto`, `Noto Sans KR`, `Oswald`, `Lobster`, `Bangers`), audio-reactive Spectrum & Waveform visualizers, B-roll PiP overlays, intro title cards, Carousel & Still Image Studio, and 6-frame Kling contact sheets.

## [v2.4.0]

## [v2.3] - 2026-10-01

### Added & Improved
- **100% Automatic Lossless Stream-Copy (`-c copy`)**: Trimming a video without changing aspect ratio or burning subtitles now automatically executes a bit-exact stream copy in ~0.1s with 0.000% generational quality loss.
- **Pro Master Formats**: Added dedicated high-fidelity export formats to Media Tools:
  - **`MP4 (4K / H.265 Master)`**: Modern HEVC compression with Apple and Windows compatible `hvc1` tags, preserving micro-details on 4K footage.
  - **`MOV (Apple ProRes 422 Studio Master)`**: 10-bit intra-frame master quality (HQ) for professional editing in Premiere Pro, DaVinci Resolve, and Final Cut.
  - **`MKV (Matroska Master)`**: Universal lossless container preserving full-fidelity audio and video streams.
  - **`WAV (Lossless PCM Audio)`**: Uncompressed 16-bit audio output.
- **Master Quality Profiles**: Added clear, intuitive quality presets in the converter:
  - **💎 Maximum Quality (Visually Lossless — 100% Detail)**: CRF 14 default, ensuring AI facial generation details, skin textures, and 4K resolution remain crisp without compression artifacts.
  - **👑 Pure Lossless (CRF 0 — Bit-Exact Copy)**: True mathematical lossless encoding pass.
  - **Standard Web (Balanced Quality)**: Standard web-optimized compression (CRF 22).
- **Interactive Click-to-Track Seamless Playback & Non-blocking Controls**:
  - Interactive face tracking overlay positioned with bottom clearance (`bottom-12`), leaving native HTML5 video controls (scrubber bar, play/pause, timecode, volume) 100% unobstructed.
  - Auto-synchronization with HTML5 video `play`, `pause`, and `seeked` events: pauses automatically to inspect clear frames, or allows clicking faces directly while playing.
  - Reticle marker decoupled from overlay layer so locked target pin remains visible during subsequent playback.
- **Auto-Shutdown Watchdog & Port Management**:
  - Client heartbeat beacon shuts down the background Python engine when the window is closed, freeing port `5000` and releasing system RAM cleanly.
- **Gallery Likes & Quick-Access Favorites**: Added 1-click heart favoriting on all gallery media cards and in the fullscreen preview modal. Includes persistent on-disk storage (`favorites.json`), a live header counter badge (`Liked (X)`), pinned heart badges on favorited cards, and 1-click quick-filtering to access liked media instantly.
- **High-Bitrate Audio Default**: AAC and MP3 encoding upgraded to 320 kbps studio bitrate.

## [v2.2] - 2026-09-30

### Added & Improved
- **YouTube Max Quality (4K Ultra HD & 2K) Support**: Added a prominent **Quality / Resolution** selector pre-selected to **🔥 Max Quality (4K / 2K / Best)** by default, with choices for 4K (2160p), 2K (1440p), 1080p, 720p, 480p, and MP3 audio.
- **Node.js JavaScript Challenge Solver**: Integrated automated Node.js challenge solving (`js_runtimes` & `remote_components: ejs:github`) into `yt-dlp` to bypass YouTube signature deciphering restrictions, unlocking pristine 4K streams without fallback throttling.
- **Universal Audio Pairing**: Video streams now pair automatically with `bestaudio[ext=m4a]` (AAC), ensuring native playback on Windows Media Player, QuickTime, and Premiere Pro without extra codecs.
- **Persistent User Preferences**: Quality choices and codec options are now automatically remembered across sessions in `localStorage`.
- **Live Trim Duration Badge & Validation**: Video Trimmer displays a live cut-duration badge with real-time feedback and validation to prevent invalid end timestamps.
- **Media Preview Lightbox Modal**: Clicking any card in the Output Gallery opens a responsive lightbox modal with embedded video, audio, and image playback, quick action buttons, and keyboard navigation (`Escape`, `ArrowLeft`, `ArrowRight`).
- **Download History Auto-Reconciliation**: Automatically scans and backfills missing files into `history.json` on startup, with downloads strictly ordered newest-first.
- **Non-blocking Windows Explorer Integration**: Folder buttons across the gallery, history, and converter now use non-blocking explorer selection with directory fallback.
- **Multi-Person Face Tracking Target Selection**: Media Tools converter now supports smart focus selection when multiple subjects are in frame:
  - 👑 **Dominant Subject**: Automatically tracks and centers the primary speaker based on face size with proximity hysteresis.
  - 🎯 **Interactive Click-to-Track**: Preview your video and click directly on any speaker's face to place a glowing purple target reticle; locks tracking onto that exact person regardless of who else speaks or moves in the scene.
  - 👈 **Left Person (Speaker 1)**: Locks onto and follows the person on the left side of the frame with left-half boundary clamping.
  - 👉 **Right Person (Speaker 2)**: Locks onto and follows the person on the right side of the frame with right-half boundary clamping.
  - 👥 **Center Framing**: Frames both speakers together, smoothly panning to keep both subjects visible in 9:16.
- **🎙️ Podcast Split-Screen Mode (Stacked 9:16)**: Added Opus Clip & CapCut style stacked layout for two-person interviews and podcasts. Simultaneously crops Speaker 1 on the top half and Speaker 2 on the bottom half with a crisp divider line, formatted directly into vertical 9:16 with zero audio re-encoding loss.
- **Temporal Centroid Tracking & Stability Fix**: Fixed sudden camera jitter and erratic switching between subjects by adding spatial-temporal continuity to the face tracker. If a subject tilts their head or looks away, the crop smoothly holds position instead of jumping across the room to other people.
- **Clean Desktop Lifecycle & Auto-Shutdown Watchdog**: Closing the app window now cleanly terminates the background Python engine after a grace period, releasing port `5000` and immediately freeing ~700 MB of system RAM. Ongoing downloads or conversions are guarded to complete safely before shutdown.
- **Smart Launcher Hot-Reload Detection**: `launch-silent.vbs` and `/api/health_check` compare on-disk file modification times with server uptime. If code files were updated, the launcher automatically reboots the server to load the latest code seamlessly.

### Fixed
- **Frame-Accurate Clip Trimming Bug**: Fixed FFmpeg duration calculation when trimming clips (`-ss <start> -t <duration>`). Setting timestamps like `00:00:14` to `00:00:28` now produces an exact 14.0-second clip instead of taking 28 seconds.
- **4K Face Tracking Divisibility by 2 Error**: Fixed `libx264` encoder failure (`width not divisible by 2 (1215x2160)`) on 4K 9:16 vertical face crops by enforcing even pixel dimensions (`1214x2160`) and adding an automatic even-dimension scaling filter.
- **Unicode UTF-8 Logging Error**: Fixed `UnicodeEncodeError` in converter debug logging when handling filenames containing special characters or fullwidth symbols (e.g. `｜`).
- **Desktop Launcher Offline Detection Bug**: Fixed COM exception handling in `launch-silent.vbs` where an offline server check was falsely detected as online due to non-short-circuiting logic, ensuring the Python backend boots reliably on launch.
- **Download History Indentation Bug**: Fixed download completion handler in `app_local.py` so downloads without frame extraction are immediately indexed into history.

## [v2.1] - 2026-09-13

### Added
- **1-Click In-App GitHub Auto-Updater (OTA)**: Users can now update the application seamlessly from the latest GitHub releases without having to re-download or reinstall the `.exe` installer or ZIP package.
- **Top Navigation Version Badge**: Displays current installed version with on-demand update checks, dynamically converting to an animated "Update Available" badge when a new release is detected.
- **Glassmorphism Update Modal**: Displays release title, release notes, published date, direct GitHub release link, real-time download/extraction progress bar, and live hot-patch status logs.
- **Safe Hot-Patch Architecture**: Safely hot-patches application code, templates, and assets while protecting user downloads (`Documents/Media Grabber`), user settings, Python runtimes (`.venv`, `python_runtime`), and version control directories.
- **Automatic Dependency Sync**: Automatically detects changes in `requirements.txt` upon updating and updates Python packages in the runtime environment.

### Fixed & Improved
- **Robust Server Restart**: Guaranteed process exit and scheduled re-launch helper preventing port collision and hanging states during restarts.
- **Code Audit & Type Safety**: Cleaned redundant `str()` conversions, eliminated uninitialized variable references, and ensured 100% test pass rate across all API endpoints.

## [v2.0] - 2026-09-09

### Added
- **1-Click Windows Setup Installer (`.exe`)**: Standalone installer powered by Inno Setup bundling an embedded portable Python 3.10 runtime. Installs in seconds without requiring Python or administrator privileges (`AI-Influencer-Media-Grabber-v2.0-Setup.exe`).
- **Modular Dependency Architecture**: Separated lightweight Core downloader dependencies (`requirements.txt`, ~80MB, fast 15-second setup) from the heavy AI Engine stack (`requirements-ai.txt`, PyTorch, Whisper, Vision BLIP, LLaMA).
- **In-App 1-Click AI Pack Installer**: Added visual AI Engine status badge in the header, an interactive AI Pack installer modal with real-time download progress and log stream, and smart auto-detection whenever an AI feature is invoked.
- **Standalone `install_ai.bat` Script**: Convenient 1-click batch script for manual or offline AI Engine pack installation.
- **Graceful Fallback & Lazy Imports**: Dynamic lazy imports in `ai_prompter.py` and `app_local.py` ensuring the application boots immediately and runs all video downloading and conversion tools with 100% reliability even when PyTorch is not yet installed.
- **Native Desktop Window Mode**: Run the app as an independent, frameless desktop window via `launch-silent.vbs` without opening browser tabs or black CMD windows.
- **In-App Live Console**: Real-time server and download engine logs streamed via Server-Sent Events (SSE) into a built-in terminal widget in the Activity panel with syntax highlighting, timestamps, and auto-scroll.
- **Output Gallery Post Links**: Direct `🔗 Visit Post` action button on all gallery media cards, allowing immediate access to the original post and influencer profile.
- **Automatic Post Link Inference**: Automatically recovers Instagram, TikTok, and YouTube URLs from existing downloaded filenames and history.
- **Companion `.url` Internet Shortcuts**: Every download automatically saves a companion Windows `.url` internet shortcut alongside the media file.
- **Desktop Shortcut Creator**: `create_shortcut.bat` and `create_desktop_shortcut.ps1` to place a one-click desktop shortcut with custom icon `assets/app_icon.ico`.
- **Exit App Button**: Clean shutdown action in the navigation header that cleanly terminates the Python engine and closes the window.
- **Retina Interface Previews**: Fresh high-resolution 2x screenshots for all 4 application tabs in `assets/`.

### Security & Privacy
- Sanitized configuration files (`pyrightconfig.json`) and added comprehensive `.gitignore` rules to ensure zero developer paths or user media data are present in distributions.
- Heavily blurred card image thumbnails in preview documentation for complete privacy.

## [v1.8] - 2026-09-02

### Added
- **Local LLM Engine**: Integrated `llama-cpp-python` with support for Llama 3 8B and Llama 3.2 1B GGUF models.
- **AI Video Summarizer & SEO**: Automatically generates comprehensive video summaries, transcript key points, and SEO hashtags (`_AI_Summary.txt`).
- **Nano Banana Prompt Enhancement**: Uses local LLMs to expand image descriptions into detailed prompt engineering keywords.
- **Decoupled Subtitle Translation**: Subtitle translation runs independently of raw audio transcription checkbox.
- **Dynamic Face-Tracking Auto-Crop (Converter)**: Converter can track the speaker's face frame-by-frame and keep them centered in vertical 9:16 format.
- **SRT Subtitle Export**: Direct `.srt` subtitle file export alongside downloaded or converted videos.

## [v1.7] - 2026-08-28

### Security & Stability
- Fixed path traversal vulnerabilities and plugged memory leaks in download tasks.
- Plugged SSE loop hangs and temporary folder creation leaks.
- Automatic RAM and VRAM garbage collection; AI models (Whisper and BLIP) now unload after 10 minutes of inactivity.
- Native keyboard shortcuts (`Ctrl/Cmd + Enter` to start tasks, `Escape` to close modals).
- Persistent `localStorage` settings across sessions.
- Auto-refreshing gallery and 2-second gallery cache to prevent filesystem thrashing.

## [v1.6] - 2026-08-20

### Added
- **AI Prompt Extractor**: Extract Nano Banana 2/Pro & GPT Image 2 optimized prompts directly from images or video frames using local PyTorch vision models (`Salesforce/blip-image-captioning-large`).
- **UI Hard Restart Button**: Added a robust Restart button to the header to reboot the local Python server with one click.
- **Auto Subtitle Burner**: Burn subtitles directly into videos using local Whisper AI transcription and FFmpeg.
- **Blurred-Background Padding (9:16)**: Convert horizontal 16:9 videos into vertical 9:16 format with a blurred background canvas.
- **iPhone 15 Pro EXIF Metadata Injector**: Inject realistic iPhone 15 Pro EXIF metadata into cleaned photos and videos in the AI Cleaner tab.
- **Fine-Tuned MB Compression Levels**: Added 50%, 75%, 80%, 85%, and 90% compression tiers with automatic GIF dimension downscaling to meet Discord 10MB limits.
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
