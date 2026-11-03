# v5.0.0 Validation Checklist (hand-off)

Run this checklist on the real machines and record results in the table at the end. The automated suites passed during development (454 Python tests, JS checks), but **nothing below has been exercised on real hardware, real accounts or a real browser yet.** Report every failure with the exact error text, the step and screenshots; do not "fix" by faking output.

Interpreter on the dev PC: `.venv\Scripts\python.exe` (Python 3.10; CI uses 3.13). Data isolation for tests: `tests/_isolation.py`.

## 0. Automated suites (any machine)
1. `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m unittest discover -s tests` → expect 454 OK.
2. `node tests/test_caption_timing.js` and `node tests/test_stream.js` → pass.
3. `Get-ChildItem static\*.js | % { node --check $_.FullName }` → no output.
4. `npm ci; npm run lint:inline` → ESLint no-undef passes on inline template scripts.
5. Python 3.13 venv: `py -3.13 -m venv .venv313; .venv313\Scripts\python -m pip install -r requirements.txt coverage; .venv313\Scripts\python -m coverage run -m unittest discover -s tests; .venv313\Scripts\python -m coverage report` → passes `fail_under` in `.coveragerc`.

## 1. Desktop PC (RTX 3080 12 GB, 32 GB RAM)
**Setup & notices**
- [x] First launch opens **Set up AI** once; *Use without AI* closes it and it does not reopen.
- [x] Header badge shows `⚡ GPU · NVIDIA GeForce RTX 3080 12 GB`, profile **GPU 12–16 GB**.
- [ ] AI Engine Pack notice lists packages and sizes (GPU pack ~2.9 GB) before anything installs; install + restart works; `python -m assets.ai_setup` verification reports `CUDAExecutionProvider`.
- [x] Each catalog row shows live size, license link, Local/Cloud; inswapper/buffalo_l/Kontext show the non-commercial badge and cannot install without the checkbox.
- [x] Downloads & Storage lists the existing files (FLUX schnell Q4, Wan 2.1 I2V Q4, inswapper) without re-downloading, and **Reclaim space** offers the duplicate `wan2.2-animate-14b-480p-Q4_0.gguf` (9.5 GB) and the old Llama 1B/8B GGUFs.
- [ ] AI Engines: existing Ollama detected; helper/translator resolve to `qwen2.5:14b` until `qwen3:14b` / `translategemma:12b` are installed; installing them through the wizard works with progress.

**Captions (the reported bug)**
- [ ] Open the Greek + English song project: previously hidden English translations are back (a `pre-v5-project.json` backup exists in the project folder).
- [ ] Edit a translation in the inline editor → wait for autosave → **Retry line karaoke** → the translation is still shown under the original.
- [ ] Edit an original line → its translation shows **⚠ Needs review** (dimmed, still visible) with Keep / Retranslate.
- [ ] Bilingual export warns about unreviewed lines (Keep all / Review / Export without them).
- [ ] English line with target English shows "Same as original (hidden)" and the per-line toggle works.
- [ ] Translate the whole song with **Auto**: Greek lines use the Translator, mixed lines the Helper (route shown), English lines kept. **A/B this line** shows both outputs.
- [ ] Transcribe / Sync lyrics uses Whisper large-v3-turbo (status shows model); timing quality vs v4 noted.
- [ ] Per-project Stop cancels only that project's job; render progress % appears.

**Downloader**
- [ ] YouTube video, YouTube `watch?v=…&list=…` (single video only), TikTok, X post.
- [ ] Instagram reel anonymously → has audio; if login wall → clear "requires login" message with Firefox / Import buttons.
- [ ] Import a cookies.txt (Firefox export) → status chip shows domains/age; IG profile listing shows posts; profile download saves only new files and never reports success with zero files.
- [ ] IG carousel photos are byte-identical to the source (compare SHA-256 with a browser download).
- [ ] Retry on a failed task works; Shazam identifies a known song (shazamio 0.9).
- [ ] Burn subtitles when the download folder is on a different drive.

**AI Studio & Copilot**
- [ ] Without the Creative engine: every generative card shows "Not available on this PC" with requirements + Set up AI (no fake output anywhere).
- [ ] Install Creative engine (ComfyUI) via wizard; then: FLUX schnell keyframe, Kontext edit with persona portrait, Wan 2.2 5B clip, Wan 2.1 14B clip (record minutes), LatentSync lip-sync, LivePortrait. Record time, VRAM peak (`nvidia-smi`), output file validity.
- [ ] Face Swap Video on a 15 s clip on GPU with GFPGAN: time, identity stays on the chosen person, original resolution/aspect, audio present, mute / project audio options.
- [ ] Responsible-use notice appears once before the first face swap / lip-sync.
- [ ] Cloud actions (only if a key is provided): cost confirmation appears; nothing is sent without it.
- [ ] Copilot (Ctrl+K) on Downloader, Captions and Studio pages: streams tokens, shows model, proposals require Apply, refuses navigation with unsaved edits, honest error + Set up AI when Ollama is stopped.

**Updater**
- [ ] Build `python build_staging.py` and install `dist\AI-Influencer-Media-Grabber-v5.0.0-Setup.exe` over v4.2.3: data preserved, app starts.

## 2. Laptop (no NVIDIA GPU or < 6 GB)
- [ ] Profile shows **Laptop / CPU** (or DirectML pack offered for Intel/AMD graphics); CPU pack ~0.3 GB notice.
- [ ] Built-in engine: install Qwen3 1.7B or 4B (by RAM) → Copilot answers and uses tools (slower); translation works offline.
- [ ] Whisper base/small transcription of a 3-minute song: record time.
- [ ] Face swap (CPU/DirectML) shows an ETA and completes; generative image/video cards show "Not available on this PC".
- [ ] Downloader, Media Tools, Captions editing and export work without any AI installed (Essentials).

## Results

| Step | Machine | Result | Time / VRAM | Notes |
|---|---|---|---|---|
| 0.1 Python unittest suite (`.venv`, Python 3.10.11) | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS (after v5.0.2 fixes) | 99.4 s | Caught transient Windows `PermissionError` in `test_orientation_applied` exposing missing `import time` in `cleaner.clean_photo` retry loop; fixed in v5.0.2 via `storage_utils.replace_with_retry` + regression test. 457 tests OK. |
| 0.2 JS unit tests (`test_caption_timing.js`, `test_stream.js`) | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 16 s | All timing, draft isolation, SSE split-boundary/UTF-8 checks passed. |
| 0.3 `node --check` on `static\*.js` | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 22 s | No syntax errors across all static JS files. |
| 0.4 `npm ci; npm run lint:inline` | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 31 s | ESLint `no-undef` passed on extracted inline template scripts. |
| 0.5 Python 3.13.9 venv (`.venv313`) + `coverage report` | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS (after v5.0.2 fixes) | 102.5 s | Initial run failed on `test_detect_nvidia_via_nvidia_smi` (`ModuleNotFoundError: No module named 'psutil'` when only `requirements.txt` is installed) and `test_zip_engine_extracts_atomically_with_marker` (`PermissionError: [WinError 5] Access is denied` on `os.replace` of `.extracting`). Fixed in v5.0.2 (`ai_core/hardware.py` OS RAM fallback + `ai_core/models.py` & `cleaner.py` `storage_utils.replace_with_retry` + 3 regression tests). 457 tests OK, 80% total coverage (`fail_under = 65`). Note: `py -3.13` launcher alias is not registered on this PC; `.venv313` created via `C:\Users\lefte\miniconda3\python.exe -m venv .venv313`. |
| 1.1 First launch opens **Set up AI** once; *Use without AI* closes it and does not reopen | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | <1 s | Verified in real headless Chrome via CDP: `.ais-sheet` opens on `/` when `setup_seen=false`, *Use without AI* sets `localStorage['mg.aiSetupSeen']='1'` and `setup_seen=true`, reload stays closed. |
| 1.2 Header badge & profile detection | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | <1 s | Header badge shows `⚡ GPU · NVIDIA GeForce RTX 3080 12 GB`, profile **GPU 12–16 GB** (`gpu_high`), Memory `32 GB RAM`. |
| 1.3 AI Engine Pack notice & install | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PARTIAL (notice PASS; awaiting OK for install) | — | Notice lists all 9 GPU pack items (`~2.9 GB` / 2,933 MB download, ~5.8 GB disk) with licenses and sources before installing. Fixed duplicated `"NVIDIA NVIDIA ..."` reason text in v5.0.3 (`assets/ai_setup.py`). Actual pack install requires moving `.venv` to Python 3.13.9 (`scipy==1.18.1` requires Python 3.11+) and user confirmation for ~2.9 GB download. |
| 1.4 Catalog row live sizes, licenses, Local/Cloud & NC gate | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 4.2 s | 40/43 catalog items return `live` size from Hugging Face / GitHub / Ollama Registry (3 GitHub codeload zips fall back to `catalog`). `inswapper-128`, `insightface-buffalo-l`, and `flux-kontext-dev-q4` display `Personal / non-commercial use only` badge and disable `Install selected` until the acceptance checkbox is ticked (and server returns 409 `ConsentRequired` without `accept_license=True`). |
| 1.5 Downloads & Storage installed list + Reclaim space | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS (after v5.0.3 fix) | 18 s (first SHA scan), <0.1 s cached | Initially existing files (`FLUX.1 schnell`, `Wan 2.1 I2V 14B`, `InSwapper 128`, `InsightFace buffalo_l`, `Whisper base`, `Qwen3 4B`) showed `Not verified` because `.verified.json` was only populated on new installs. Fixed in v5.0.3 (`ai_core/models.py` `storage()` verifies matching existing files and caches in `.verified.json`). **Reclaim space** offers duplicate `wan2.2-animate-14b-480p-Q4_0.gguf` (9.5 GB, duplicate of `wan2.1-i2v-14b-480p-Q4_0.gguf`) and old `Llama-3.2-1B-Instruct-Q4_K_M.gguf` (770 MB) + `Meta-Llama-3-8B-Instruct.Q4_K_M.gguf` (4.6 GB), total 14.9 GB. |
| 1.6 AI Engines detection & role resolution | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PARTIAL (detection/resolution PASS; awaiting OK to download `qwen3:14b` / `translategemma:12b`) | <1 s | Existing Ollama `v0.40.14` detected and `Running`; `Helper` and `Translator` both resolve to `qwen2.5:14b · ollama · ~20 s per answer · 9.6 GB VRAM`. |
