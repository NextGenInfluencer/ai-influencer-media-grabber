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
- [x] AI Engine Pack notice lists packages and sizes (GPU pack ~2.9 GB) before anything installs; install + restart works; `python -m assets.ai_setup` verification reports `CUDAExecutionProvider`.
- [x] Each catalog row shows live size, license link, Local/Cloud; inswapper/buffalo_l/Kontext show the non-commercial badge and cannot install without the checkbox.
- [x] Downloads & Storage lists the existing files (FLUX schnell Q4, Wan 2.1 I2V Q4, inswapper) without re-downloading, and **Reclaim space** offers the duplicate `wan2.2-animate-14b-480p-Q4_0.gguf` (9.5 GB) and the old Llama 1B/8B GGUFs.
- [x] AI Engines: existing Ollama detected; helper/translator resolve to `qwen2.5:14b` until `qwen3:14b` / `translategemma:12b` are installed; installing them through the wizard works with progress.

**Captions (the reported bug)**
- [x] Open the Greek + English song project: previously hidden English translations are back (a `pre-v5-project.json` backup exists in the project folder).
- [x] Edit a translation in the inline editor → wait for autosave → **Retry line karaoke** → the translation is still shown under the original.
- [x] Edit an original line → its translation shows **⚠ Needs review** (dimmed, still visible) with Keep / Retranslate.
- [x] Bilingual export warns about unreviewed lines (Keep all / Review / Export without them).
- [x] English line with target English shows "Same as original (hidden)" and the per-line toggle works.
- [x] Translate the whole song with **Auto**: Greek lines use the Translator, mixed lines the Helper (route shown), English lines kept. **A/B this line** shows both outputs.
- [ ] Transcribe / Sync lyrics uses Whisper large-v3-turbo (status shows model); timing quality vs v4 noted.
- [x] Per-project Stop cancels only that project's job; render progress % appears.

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
| 1.3 AI Engine Pack notice & install | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS (after v5.0.3 fix) | ~3 min install | Notice lists all 9 GPU pack items (`~2.9 GB` / 2,933 MB download, ~5.8 GB disk) with licenses and sources before installing. Fixed duplicated `"NVIDIA NVIDIA ..."` reason text in v5.0.3 (`assets/ai_setup.py`). Recreated `.venv` on Python 3.13.9 (`C:\Users\lefte\miniconda3\python.exe -m venv .venv`), installed GPU pack via `python -m assets.ai_setup --install --pack gpu --yes`, and verified `python -m assets.ai_setup --pack gpu` reports `onnx_providers: ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]` and `/api/ai_status` reports `all_installed: true`. |
| 1.4 Catalog row live sizes, licenses, Local/Cloud & NC gate | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 4.2 s | 40/43 catalog items return `live` size from Hugging Face / GitHub / Ollama Registry (3 GitHub codeload zips fall back to `catalog`). `inswapper-128`, `insightface-buffalo-l`, and `flux-kontext-dev-q4` display `Personal / non-commercial use only` badge and disable `Install selected` until the acceptance checkbox is ticked (and server returns 409 `ConsentRequired` without `accept_license=True`). |
| 1.5 Downloads & Storage installed list + Reclaim space | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS (after v5.0.3 fix) | 18 s (first SHA scan), <0.1 s cached | Initially existing files (`FLUX.1 schnell`, `Wan 2.1 I2V 14B`, `InSwapper 128`, `InsightFace buffalo_l`, `Whisper base`, `Qwen3 4B`) showed `Not verified` because `.verified.json` was only populated on new installs. Fixed in v5.0.3 (`ai_core/models.py` `storage()` verifies matching existing files and caches in `.verified.json`). **Reclaim space** offered and removed duplicate `wan2.2-animate-14b-480p-Q4_0.gguf` (9.5 GB) and obsolete `Llama-3.2-1B-Instruct-Q4_K_M.gguf` (770 MB) + `Meta-Llama-3-8B-Instruct.Q4_K_M.gguf` (4.6 GB), freeing 14.9 GB (`removed_count: 3`). |
| 1.6 AI Engines detection & role resolution | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 116.1 s (`qwen3:14b`), 104.2 s (`translategemma:12b`) | Existing Ollama `v0.40.14` detected and `Running`; before install `Helper` and `Translator` resolved to `qwen2.5:14b`. Installed `qwen3:14b` (9.28 GB) and `translategemma:12b` (8.11 GB) with live byte progress; afterwards `Helper` resolves to `qwen3:14b · ollama · ~20 s per answer · 10.5 GB VRAM` and `Translator` resolves to `translategemma:12b · ollama · ~20 s per answer · 9 GB VRAM`. |
| 1.7 Open Greek + English song project (`bc37381315734657bcd366c014b0988e`) | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | <1 s | Opening `'08. Ανάσα (Breath) [feat. Airi Oh].wav'` created `pre-v5-project.json`, applied `v5_translation_source` migration, and repaired line #29 (`'Ξέχασα πια τι πάει να πει'`, whose `source` was raw Greek text from the v4.x inline editor bug) to `status: "approved"`, `source: "16b346e6..."`, displaying `🌐 I've forgotten what it means` in `#cueList`. |
| 1.8 Edit translation inline → autosave → Retry line karaoke | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 2.1 s | Edited line #4 translation in `#sideTranslationText` on a disposable project duplicate, waited for `All changes saved`, clicked `#karaokeLine` (`Retry line karaoke`); 5 words aligned and translation remained `status: "approved"` (`🌐 I really didn't feel like going out tonight`) under the original. |
| 1.9 Edit original line → `⚠ Needs review` with Keep / Retranslate | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | <1 s | Editing original line #4 marked its translation `status: "stale"`, showed `⚠ Needs review · ...` dimmed (`opacity: 0.55`) in `#cueList`, and surfaced `#translationReviewBox` with enabled **Keep** (`#keepTranslation`) and **Retranslate** (`#retranslateLine`) buttons. |
| 1.10 Bilingual export guard on unreviewed lines | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | <1 s | Clicking `#bilingualSrt` opened `#exportGuardDialog` (`1 line needs review`) listing `Changed line #4` with **Keep all**, **Review**, and **Export without them**; **Review** selected `Line #4`, and **Keep all** approved the line and proceeded. |
| 1.11 English line with target English shows "Same as original (hidden)" + per-line toggle | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | <1 s | Selecting English line #2 (`'My boys pulled me out of my bed'`) showed `#duplicateNote` (`Same as original (hidden)`); toggling `#showDuplicateTranslation` ON added the translation row to `/api/captions/<pid>/layout` and toggling OFF hid it again. |
| 1.12 Translate whole song with **Auto** + **A/B this line** | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS (after v5.0.4 fixes) | 8.4 s (A/B), 11.2 s (batch) | Found and fixed 3 issues: (1) English lines with `'a'` or `'no'` (`'Cutting through sadness like a knife'`, `'No turning back'`) were misclassified as `pt`/`es` because `'a'`/`'no'` were missing from `STOPWORDS['en']` in `ai_core/translate.py`; (2) `translate_project` in `captions.py` pre-seeded `chorus` with unlocked lines inside `pending`, skipping re-translation of already-approved lines; (3) `showTranslationReview` in `static/captions.js` did not display `entry.route`. After fixes: **A/B this line** shows `Translator · translategemma:12b · Local` and `Helper · qwen3:14b · Local` side by side; **Auto** routes English lines to `same` (`Same as original`), Greek lines to `translator` (`Translator`), and mixed lines to `helper` (`Helper (mixed language)`). |
| 1.13 Transcribe / Sync lyrics with Whisper `large-v3-turbo` | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PARTIAL (status model label added in v5.0.4; awaiting OK to download `whisper-large-v3-turbo`) | — | Updated `/transcribe` and `/align` in `captions.py` to include `Whisper <model>` in running and completion status messages. Currently `whisper-base` is installed; awaiting user confirmation to download `whisper-large-v3-turbo` (1.62 GB, OpenAI, MIT license) to run timing comparison. |
| 1.14 Per-project Stop isolation & render progress % | Desktop PC (RTX 3080 12 GB, 32 GB RAM) | PASS | 2.8 s | Started concurrent renders on two project duplicates; status displayed `Exporting captioned video… 0%` / `6%`; cancelling project A stopped only project A (`Cancelled by user`, saved captions preserved) while project B remained `busy` and continued rendering. |
