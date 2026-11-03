# Hand-off: state of the project after v5.0.1

Read this file first, then `AGENTS.md` (workspace rules), `docs/v5-architecture.md` (module contract) and `docs/v5-validation.md` (test checklist).

## What this app is
A **public, free Windows app** for AI-influencer creators. The core rule is that the creator never has to open another app. It installs small and works fully without AI: downloader, Media Tools, AI Cleaner, Captions Studio, gallery. AI is **opt-in**: the app detects the PC, recommends a profile, and downloads nothing without showing the size, source and license first. It must run on laptops without a GPU (smaller models) as well as on the owner's RTX 3080 12 GB PC (best free models). **Nothing may be faked:** if a capability is missing, say so (`AIUnavailable` → HTTP 424 + `setup_hint` → "Not available on this PC" + Set up AI).

## Current state (main @ v5.0.1, tags v5.0.0 / v5.0.1 pushed)
- Automated: 454 Python tests pass (`$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m unittest discover -s tests`). JS checks pass.
- **Not yet validated on real hardware, in a browser, or with real accounts.** This is the main open work: run `docs/v5-validation.md`.
- GitHub Release (with Setup.exe) not yet published. The in-app updater only sees Releases, not tags.

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
1. Run `docs/v5-validation.md` on the PC, then on the laptop (section 2), and fix what fails. Highest-risk areas:
   - the ComfyUI workflows (never run against a real ComfyUI)
   - the Copilot drawer in the browser
   - Shazam after the shazamio 0.9 upgrade
   - IG profile listing with an imported cookies.txt
   - face swap on GPU/DirectML
2. The dev machine shows AI "not installed" until the AI pack is reinstalled (new required module `keyring`).
3. Vocal isolation: `audio-separator` is in no pack (Python 3.13 install issues). The model `uvr-kim-vocal-2` is in the catalog but not in bundles. Add it back once the library installs cleanly.
4. OTA cannot delete files that a release removes.
5. Dev venv is Python 3.10; the installer and CI use 3.13. Move the dev venv to 3.13.
6. Publish a GitHub Release with `dist\AI-Influencer-Media-Grabber-vX.Y.Z-Setup.exe` (`python build_staging.py`, needs Inno Setup 6) and a SHA256 file.
