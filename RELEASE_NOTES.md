# v2.4.1 — Nano Banana character-swap prompts

- Generated prompts now assign the original first frame and influencer reference distinct roles.
- Preserve pose, framing, original clothing, background, and lighting while replacing identity.
- Remove cinematic styling and invented quality keywords; automatic scene captions are explicitly secondary to the images.
- Optional local AI rewriting now preserves the editing constraints.

Compatible with the v2.4.0 in-app updater; restart after applying. Existing prompt text files are unchanged. Prompt output still needs validation with your own images in Nano Banana.

# v2.4.0 — Reference preparation and reliability

Use the Windows installer for the upgrade from v2.3. This release includes Python 3.13.16, Node 26.9.0, and a pinned core dependency set. The old v2.3 source updater cannot migrate its bundled runtime safely.

- Kling Prep creates a matching reference video and first-frame PNG, accepts your Nano Banana edited image, and exports a reusable set. The first frame remains the default.
- Local file access and browser requests are protected; unsafe filenames and remote HTML are escaped. Failed recycle-bin operations preserve files.
- Conversion honors edits and subtitle settings, validates ranges and crops, reports encoder failures, and writes distinct outputs.
- Cleaner preserves originals and orientation; animated files are rejected explicitly rather than flattened. Its descriptions no longer promise to bypass detection.
- Playlist and photo-carousel items share post-processing. History stays deleted, and custom download folders persist in the gallery.
- Stop jobs cancels active external encoders/download helpers and stops subsequent processing. An AI call already running finishes its current step before stopping; Exit remains blocked until work ends.
- AI loading, inference and unloading are serialized. Subtitle translation preserves cue IDs and timing and translates each cue in the selected language.
- Future compatible source updates are staged, checked for unsafe archive paths and dependency changes, syntax-checked and startup-tested before restart. Applying files keeps backups and restores them on interrupted/failed activation. Dependency/runtime migrations use an installer.
- Styling/icons and the downloader JavaScript runtime are bundled. Startup no longer silently upgrades dependencies.

## Validation and practical limits

Automated checks use generated media, an isolated library, deterministic downloader/model fixtures, and real FFmpeg encoders. They cover failure recovery, not only success paths. Real account downloads, live music recognition, large AI model inference, and external Kling/Nano Banana uploads still depend on their services and have not been certified by these tests.

Kling Prep prepares matching files; it does not score pose/identity similarity or contact external AI services. GIF animation is handled by conversion, not metadata cleaning. The gallery uses a cached filesystem listing; a database index and additional content-planning features remain future enhancements. Updates trust this GitHub repository over HTTPS; they are not independently signed releases.
