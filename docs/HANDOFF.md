# Hand-off: state of the project after v5.0.8

Read this file first, then `AGENTS.md` (workspace rules), `docs/v5-architecture.md` (module contract) and `docs/v5-validation.md` (test checklist).

## What this app is
A **public, free Windows app** for AI-influencer creators. The core rule is that the creator never has to open another app. It installs small and works fully without AI: downloader, Media Tools, AI Cleaner, Captions Studio, gallery. AI is **opt-in**: the app detects the PC, recommends a profile, and downloads nothing without showing the size, source and license first. It must run on laptops without a GPU (smaller models) as well as on the owner's RTX 3080 12 GB PC (best free models). **Nothing may be faked:** if a capability is missing, say so (`AIUnavailable` → HTTP 424 + `setup_hint` → "Not available on this PC" + Set up AI).

## Current state (main @ v5.0.8, v5.0.8 published and validated)
- Automated: 474 Python tests pass (`$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m unittest discover -s tests`). JS unit tests, `node --check`, and ESLint `no-undef` on inline template scripts pass.
- **Validated on real hardware (`docs/v5-validation.md` sections 0–2 passed):**
  - Section 0 (automated suites + Python 3.13 coverage): PASS.
  - Section 1 (Desktop PC — RTX 3080 12 GB, 32 GB RAM): PASS across Setup & notices, Captions Studio, Downloader, AI Studio (all 6 local ComfyUI workflows + GPU Face Swap with CUDA 13), Copilot, and Setup.exe upgrade over v4.2.3.
  - Section 2 (Laptop — Intel Core i5-8250U, 16 GB RAM, Intel UHD Graphics 620): PASS across Laptop/DirectML pack setup, built-in CPU LLM (`qwen3-1.7b`) Copilot & offline lyric translation, Whisper CPU transcription (`base` / `small`), DirectML Face Swap with live ETA, and Essentials non-AI workflows.
- GitHub Release **v5.0.8** is published and validated on both PC and laptop.

## Architecture in one minute
- `ai_core/`: everything AI.
  - `hardware.py`: profiles `essentials / laptop / gpu_mid / gpu_high / gpu_ultra`.
  - `catalog.json`: pinned models with sha256, size, license and NC flags, plus bundles and recommendations per profile.
  - `models.py`: consent-gated installs, `ensure()` never downloads.
  - `gpu.py`: VRAM broker.
  - `engines.py`: Ollama, Built-in llama.cpp and ComfyUI processes.
  - `llm.py`: role router (`helper`, `translator`, `vision`, `speech`).
  - `translate.py`: per-line routing: same-language lines kept, single-language lines → translator, mixed lines → helper.
  - `asr.py`, `vision.py`, `face.py`, `comfy.py` (+ `workflows/*.json`), `cloud.py` (opt-in only; keys in keyring).
- `routes_ai.py`: `/api/ai/*` (profile, catalog, notice, install, jobs, storage, engines, settings, cloud keys).
- `routes_studio.py`: AI Studio, motion and characters routes, async `/api/jobs/<id>`.
- `copilot.py` + `static/copilot.js`: agent loop with tools, proposals before applying, SSE `/api/copilot/chat/stream`.
- `captions.py` + `static/captions.js`: Captions Studio. The translation record contract: `source = sha256(normalize_ws(text))`. The only writers are `setCueTranslation()` (JS) and `lyric_tracks.make_translation()` (Python).
- `download_support.py` + `app_local.py`: downloads, cookies (`/api/cookies/*`), history, gallery, updater.
- `static/ai_setup.js`: Setup wizard (`window.openAISetup`), AI Engines, Downloads & Storage, first-use notices (`window.ensureNoticeAccepted`).
- `storage_utils.py`: atomic JSON writes with Windows retry.
- `safe_update.py` + `release_manifest.json`: OTA updates. Updates that change any `requirements*.txt` are refused; those need the full installer.

## Rules that must keep holding
1. **Never fake AI output**, and never report success without a real result.
2. **No silent downloads.** Only `ai_core.models.start_install(item, accept_license=True)` downloads, after the user saw the notice.
3. **Lyrics never go to the cloud** unless the user explicitly chooses a cloud action. Keep the Ollama locality guard.
4. **Never modify or delete user media, projects, history or credentials.** Migrations write a backup first.
5. **Bump the version on every change:**
   - Files: `APP_VERSION` in `app_local.py`, `MyAppVersion`/`OutputBaseFilename`/`VersionInfoVersion` in `installer.iss`, and `build_staging.py`.
   - Add a CHANGELOG entry.
   - Commit, create the tag `vX.Y.Z` and push both.
6. Add a regression test for every fix, and keep the full suite green.
7. UI follows the Apple-Pro style in `AGENTS.md`.

## Known open items (priority order)
1. ~~**Download engine updates without a full installer:**~~ **(Done in v5.0.9)**
2. ~~**Vocal isolation:**~~ **(Done in v5.0.10)**
3. **OTA cleanup:** remove app files that are no longer in the new release manifest, with a backup. Never touch user data, `history.json`, cookies, custom fonts, models or engines.
4. **Move the PC dev venv to Python 3.13 (`.venv`)** and confirm the full suite passes.
5. **Retake the README screenshots in `assets/`** from the v5 UI.
