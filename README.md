# AI Influencer Media Grabber v2.4.0

Download reference media, edit/convert files locally, and prepare matching video/image sets for your Nano Banana → Kling workflow.

For an existing v2.3 installation, use the v2.4.0 Windows installer. This updates the bundled runtime as well as the app. Your Documents/Media Grabber library is retained. See [release notes](RELEASE_NOTES.md) and [workflow details](IMPLEMENTATION_NOTES.md).

Source development requires Python 3.13 and Node 26. Install `requirements.txt`, then run `app_local.py`. Run `python -m unittest discover -s tests -v` and `node tests/test_stream.js` before release. Build with `python build_staging.py`; Inno Setup 6 produces the Windows installer. Cached runtime downloads are verified against pinned SHA-256 values.

The optional AI Pack requires additional downloads and several GB of storage. Media processing is local; downloads, model acquisition, release checks, and music recognition use online services. Metadata cleanup does not guarantee removal of watermarks or AI detection signals.
