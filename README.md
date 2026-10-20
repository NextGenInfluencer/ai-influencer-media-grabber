# AI Influencer Media Grabber v2.5.0

Download reference media, edit/convert files locally, and prepare matching video/image sets for your Nano Banana → Kling workflow.

For an existing v2.3 or v2.4.x installation, use the v2.5.0 Windows installer. This updates the bundled runtime as well as the app. Your Documents/Media Grabber library is retained. See [release notes](RELEASE_NOTES.md) and [workflow details](IMPLEMENTATION_NOTES.md).

Source development requires Python 3.13 and Node 26. Install `requirements.txt`, then run `app_local.py`. Run `python -m unittest discover -s tests -v` and `node tests/test_stream.js` before release. Build with `python build_staging.py`; Inno Setup 6 produces the Windows installer. Cached runtime downloads are verified against pinned SHA-256 values.

The optional AI Pack requires additional downloads and several GB of storage. Media processing is local; downloads, model acquisition, release checks, and music recognition use online services. Metadata cleanup does not guarantee removal of watermarks or AI detection signals.

## Captions & Lyrics

Open **Captions & Lyrics** from the Studio navigation. Upload a video or select one from the library, then auto-transcribe with the optional AI Pack, paste lyrics, or import SRT/LRC subtitles. Edit text and timing on the waveform timeline; select fonts, colors, position, backgrounds, or karaoke highlighting while watching the live preview. Changes autosave; undo/redo remains available for the current editing session.

Pasted lyrics and the **Estimate word timings** button distribute text evenly. They do **not** align lyrics to vocals. Adjust these estimates manually while listening. Automatic transcription supplies word timings when available, but both its words and timings need review, especially for songs. Editing a caption's text clears its old word timings.

Use **Render 5-second check** at the playhead to inspect actual export typography, which may differ from browser layout. **Export captioned MP4** creates a new full-resolution H.264 video; original files remain unchanged. SRT export contains text and timing, not styling. Projects and exports live under `Caption Projects` in the media library. The first version supports videos up to two hours, 8192 pixels per dimension, and 5,000 caption lines.

Upgrade to v2.5.0 using the Windows installer: the v2.4.1 updater's old file allowlist does not include the new `captions.py` module. See [implementation plan](CAPTIONS_PLAN.md).
