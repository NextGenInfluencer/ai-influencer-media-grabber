# Continuous integration and packaging notes

## CI (`.github/workflows/checks.yml`)

Runs on `windows-latest` with Python 3.13 and Node 26 on every push and pull request:

1. `pip install --only-binary=:all: -r requirements.txt` (core only) and `coverage`.
   The AI Engine Pack is not installed: AI tests mock those libraries.
2. `python -m coverage run -m unittest discover -s tests`, then `coverage report`.
   The gate is the global `fail_under` in `.coveragerc` (currently **65 %**). It was
   measured at **69 %** on the v5 platform branch (259 tests); the margin absorbs small
   differences between Python versions. Raise it as coverage improves; never lower it to
   make a change pass. New shared modules are covered much higher (`storage_utils.py`
   100 %, `safe_update.py` 96 %, `assets/ai_setup.py` 87 %).
3. `node --check` on every `static/*.js`.
4. `python tools/extract_inline_js.py` writes the inline `<script>` blocks of
   `templates/*.html` to `build/inline-js/` (template line numbers are preserved), then
   `npx eslint build/inline-js` runs `no-undef` with browser globals
   (`eslint.config.mjs`). Names declared at top level by a page's own `/static/*.js`
   files are declared automatically.
5. JavaScript tests: `tests/test_caption_timing.js`, `tests/test_stream.js`.

Run the same checks locally:

```powershell
npm ci
python tools/extract_inline_js.py; npx eslint build/inline-js
python -m coverage run -m unittest discover -s tests; python -m coverage report
```

`package.json` / `package-lock.json` are development tooling only and are not part of
releases.

## Release payload (`release_manifest.json`)

The manifest lists what a release contains: every top-level `*.py`, the launchers,
requirement files, `ai_packs.json`, the notices and the `assets/`, `static/`,
`templates/`, `docs/` and `ai_core/` folders. It is used by:

- `build_staging.py` to copy files into the installer staging folder, and
- the in-app updater (`safe_update.py`), which reads the manifest **from the downloaded
  archive**, validates every entry (no absolute paths, no `..`, only the allowed roots,
  never user data such as `history.json` or `static/fonts/custom/`), and falls back to
  its built-in list for archives without a manifest.

Updates that change any `requirements*.txt` file are refused in-app and need the
release installer. Only the two newest `.updates/backup-*` recovery folders are kept.

## AI Engine Packs

| Pack | File | Chosen when |
|---|---|---|
| CPU | `requirements-ai-cpu.txt` | No supported GPU |
| CPU + DirectML | `requirements-ai-directml.txt` | Windows with Intel/AMD graphics (or an NVIDIA GPU under 6 GB) |
| NVIDIA GPU (CUDA 12.6) | `requirements-ai-gpu.txt` | NVIDIA GPU with at least 6 GB of video memory |

All three include `requirements-ai-common.txt` and are constrained by
`requirements.txt`. After the pack, `requirements-ai-nodeps.txt` (InsightFace) is
installed with `--no-deps`, because InsightFace declares `opencv-python` and
`onnxruntime`, which would overwrite the core `opencv-python-headless` and the
GPU/DirectML ONNX Runtime. `requirements-ai.txt` remains as a thin compatibility file
that includes the CPU pack for older scripts.

Sizes and licenses shown in the pre-install notice come from `ai_packs.json` (measured
for the pinned Windows/Python 3.13 wheels). All packs were resolved together with the
core lock for Windows x64 / CPython 3.13 before release.

`audio-separator` (vocal isolation) is intentionally not in any pack: on Python 3.13 its
current releases require nightly `onnx-weekly` builds that clash with `onnx`, and older
releases need a compiler.

## Known lint findings at the time this gate was added

`npx eslint build/inline-js` reports these real bugs in `templates/index.html`, owned
by the downloader/UI work:

- `uuidv4` is undefined (Retry button).
- `syncTrackingUI` is called from the file-selection handler but is defined inside a
  `DOMContentLoaded` callback, so the `typeof` guard always skips the call.

The CI lint step fails until they are fixed.
