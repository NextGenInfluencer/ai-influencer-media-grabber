# v5.0.0 Architecture Contract

This document is the shared contract for the v5.0.0 work. Modules written in
parallel must follow these interfaces exactly so they integrate without
rework. The approved plan is the source of truth for scope; this file defines
names, signatures and ownership.

## Principles (non-negotiable)

1. **Nothing fake.** No procedural/placeholder output may be reported as AI
   output. If a capability is missing, raise `ai_core.errors.AIUnavailable`
   with a user-facing message and a `setup_hint` (catalog item id or
   settings section). UI shows an elegant "Not available on this PC" state.
2. **No silent downloads.** Model/engine weights are only downloaded by
   `ai_core.models.start_install(item_id, accept_license=True)` after the user
   confirmed a notice. Every other code path calls `ai_core.models.ensure()`,
   which returns a local path or raises `ModelMissing` (subclass of
   `AIUnavailable`). Libraries that auto-download (whisper, transformers,
   insightface, huggingface_hub) must be called with local paths only.
3. **Lyrics never leave the PC** unless the user explicitly chose a cloud
   provider for that action. The Ollama locality guard
   (`require_local_ollama_model`) stays mandatory for every Ollama call.
4. **User data is never modified** except migrations that write a backup
   first. Media files are stored byte-exact.
5. **Every AI action exposes its cost**: `{local: bool, model, eta_seconds,
   vram_gb}` via `ai_core.llm.resolve()` / catalog metadata.

## Package layout: `ai_core/`

| Module | Responsibility |
|---|---|
| `errors.py` | `AIUnavailable(message, setup_hint=None)`, `ModelMissing(AIUnavailable)`, `ConsentRequired(AIUnavailable)` |
| `paths.py` | `DATA_DIR` (honours `MEDIA_GRABBER_DATA_DIR`), `MODELS_DIR = DATA_DIR/'models'`, `ENGINES_DIR = DATA_DIR/'engines'`, `SETTINGS_FILE = DATA_DIR/'ai_settings.json'` |
| `settings.py` | `load() -> dict`, `save(dict)`, `get_role_override(role)`, `accepted_licenses()`, `accept_license(item_id)` |
| `hardware.py` | `detect() -> dict` (`gpu_vendor`, `gpu_name`, `vram_gb`, `ram_gb`, `disk_free_gb`, `os`), `profile(info=None) -> str` in `PROFILES = ('essentials','laptop','gpu_mid','gpu_high','gpu_ultra')`, `current_profile()` (honours settings override) |
| `catalog.json` / `catalog.py` | Pinned item metadata; `items()`, `get(item_id)`, `recommended(profile, role) -> list[item_id]` (ordered best→fallback) |
| `models.py` | `status() -> dict[item_id, {installed, verified, path, size_bytes}]`, `notice(item_id) -> dict` (live size, license, features, source, local/cloud, NC flag), `start_install(item_id, accept_license=False) -> job_id` (raises `ConsentRequired` for NC/unaccepted licenses), `job(job_id)`, `cancel(job_id)`, `remove(item_id)`, `reclaimable() -> list` (hash duplicates + obsolete files), `ensure(item_id) -> Path` |
| `gpu.py` | `lease(name, vram_gb)` context manager; `register_evictor(name, fn)`; `model_lock(name) -> RLock`; `touch(name)` + idle release *after last use* |
| `engines.py` | `ollama.status()`, `ollama.ensure_running()`, `ollama.base_url`; `builtin.available()`; `comfy.status()`, `comfy.ensure_running()`, `comfy.stop()` |
| `llm.py` | `resolve(role) -> {backend:'ollama'|'builtin', model, local:True, profile}`; `chat(role, messages, *, tools=None, schema=None, images=None, max_tokens=1024, temperature=0.3, on_token=None, model=None) -> {content, tool_calls, model, backend}`; `available_models() -> list[dict]` (with capabilities) |
| `asr.py` | `whisper_model_name()`, `get_model()` / `release()`, `transcribe(audio, *, language=None, word_timestamps=True, vad=True)`, `detect_language(samples, candidates=None)`, `align(audio, text, language)`, `align_words(audio, text, language)`, `isolate_vocals(path) -> Path` (raises `AIUnavailable` when not installed) |
| `translate.py` | `classify_line(text, target) -> 'same' | 'single' | 'mixed'` plus detected source language; `translate_lines(lines, target, *, context='', glossary='', notes='', model=None) -> dict[id, {text, note, route}]` with route in `same|translator|helper` |
| `vision.py` | `caption(image) -> str`, `describe_scene(image) -> dict`, `profile_from_portrait(image) -> dict`, `rank_frames(paths) -> list[int]` |
| `face.py` | `swap_image(target, source, output, *, restore=True) -> dict`, `swap_video(target_video, source_image, output, *, restore=True, progress=None) -> dict` (no frame cap, keep resolution/aspect, keep identity, remux audio, raise on no face) |
| `comfy.py` | `run_workflow(name, inputs, *, progress=None) -> list[Path]`; workflows under `ai_core/workflows/` |
| `cloud.py` | `has_key(provider)`, `set_key(provider, key)` (keyring), `masked(provider)`, `kling_motion_control(image, video, **opts)`, `live_portrait(image, video)`, `nano_banana_edit(images, prompt)`; all raise `AIUnavailable` when disabled, never called implicitly |

### Roles

`helper` (Copilot, director, social copy, mixed-language lines), `translator`
(single-language lyric lines), `vision`, `speech`.

### Profiles → default recommendations

| Profile | Detection | helper | translator | speech | vision |
|---|---|---|---|---|---|
| essentials | AI pack not installed | — | — | — | — |
| laptop | no NVIDIA GPU with ≥6 GB | builtin `qwen3-1.7b` (<16 GB RAM) / `qwen3-4b` | same as helper (optional `translategemma-4b-gguf`) | `base` (<16 GB RAM) / `small` | `blip-base` |
| gpu_mid | NVIDIA 6–10 GB | `qwen3:8b` | `translategemma:4b` | `large-v3-turbo` | `qwen2.5vl:3b` |
| gpu_high | NVIDIA 10–20 GB | `qwen3:14b` | `translategemma:12b` | `large-v3-turbo` | `qwen2.5vl:7b` |
| gpu_ultra | NVIDIA ≥20 GB | `qwen3:32b` | `translategemma:27b` | `large-v3` | `qwen2.5vl:32b` |

Installed Ollama models with matching capabilities (e.g. an existing
`qwen2.5:14b`) are accepted as fallbacks for their role.

## Flask integration

New HTTP routes live in blueprints, not in `app_local.py`:

| Blueprint module | Prefix | Owner |
|---|---|---|
| `routes_ai.py` | `/api/ai/*` (profile, models, notices, installs, storage, engines, settings, cloud keys) | AI core workstream |
| `routes_studio.py` | `/api/video-studio/*`, `/api/motion/*`, `/api/jobs/*` | Studio workstream |
| `captions.py` (existing) | `/api/captions/*` | Captions workstream |

`app_local.py` only registers blueprints and keeps download/gallery/history/
convert/update routes.

## Shared utilities

- `storage_utils.atomic_write_json(path, data)` and
  `storage_utils.atomic_write_text(path, text)`: temp file + `os.replace`
  with retry/backoff on Windows `PermissionError` (5 attempts, 50→800 ms).
- `storage_utils.read_json_with_backup(path, default)`: reads, falls back to
  `.bak`, preserves corrupt files as `*.corrupt-<ts>.json`.

## Translation record contract (captions)

`cue.translations[lang] = {text, source, status, locked, note}` where
`source` is **always** `sha256(normalize_ws(cue.text))` (`normalize_ws`
collapses whitespace runs and strips). The only writers are
`setCueTranslation()` in `captions.js` and
`lyric_tracks.make_translation()` on the server.
