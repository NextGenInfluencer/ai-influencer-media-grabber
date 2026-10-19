# Kling preparation and reliability update

Release implementation completed on 19 October 2026. See RELEASE_NOTES.md for upgrade instructions and validation limits.

## Use the new workflow

Restart the app from this project and choose **Kling Prep**.

1. Select a reference video. The start defaults to zero: the video is copied without re-encoding and its first frame is saved as PNG.
2. Optionally pause at another point and choose **Use current position**. Preparing the set creates a trimmed H.264 video and extracts the first frame from that exported clip, keeping them aligned.
3. Save `first_frame.png` and edit the character in Nano Banana as usual.
4. Add your edited influencer image. Compare it beside the original frame. Dimensions must match; optional resizing is available for images with the same aspect ratio. The app does not judge pose or identity similarity.
5. Download the matched ZIP or open the project folder. The ZIP contains the reference video, original first frame, influencer image, and a short usage note.

Reference sets are stored under `Documents/Media Grabber/Kling References` and can be reopened from the saved-set selector. Original uploaded videos remain alongside their derivatives. Nano Banana and Kling are still used manually; the app does not send media to either service. This prepares matching files, but does not validate every model-specific platform upload limit.

## Reliability changes

- Restrict library file access; session, origin, host, and request-token checks protect the local service. Explicitly browsed external media can be previewed. Executables cannot be opened through the media route.
- Escape remote titles, uploader names, and URLs before rendering them in the interface.
- Sanitize conversion filenames and allowlist output formats.
- Recycle-bin failures preserve the file; they no longer fall back to permanent deletion.
- Cleaner batches create distinct outputs, preserve source files, and deduplicate by content rather than pathname. Backups have unique destinations and failures stop processing.
- Animated and multipage images are explicitly rejected by the cleaner without modification. Animation editing remains available through the converter; the cleaner no longer silently flattens GIFs.
- Apply photo orientation before metadata changes, and keep video containers consistent with their extensions.
- Fit portrait/landscape crops within the source dimensions.
- Remove automatic stream-copy trimming that skipped codecs and subtitles. Current conversion trims re-encode and can take longer; an explicit fast-cut mode remains future work.
- Validate trim ranges and report missing subtitle engines as failures rather than successful exports.
- Keep long-running progress streams alive, buffer split UTF-8/SSE events, and retain cancellation state until the download worker exits.
- Reject Exit/Restart while counted jobs are running. Cleaner and reference preparation participate in that count. The launcher reuses an existing server instead of sending an unauthenticated shutdown request.
- Include the new Python modules, templates, and static assets in installer staging.

## Verification

38 Python regression checks cover generated MP4/WebM media, HEVC trimming with SRT output, image orientation, safe filenames and file reads, recycle-bin failure, content deduplication, split idle-job behavior, reference-frame matching, image import, and ZIP contents. Subtitle tests use a deterministic transcription stub; they do not download or test Whisper models.

JavaScript checks cover split events at every byte boundary, Unicode text, and script syntax. An isolated browser preview verified opening the new screen, video selection and preparation, reopening a saved set, and rendering both comparison images. The test library is separate from personal media.

Run with the existing project environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_stream.js
```

## Follow-up reliability work

The release adds staged/recoverable source updates, cancellation checks and external-process termination, AI inference serialization, cue-preserving translation, playlist/carousel post-processing, persistent custom library roots, one-time history migration, bundled UI assets and Node, pinned core dependencies, a supported Python runtime, and automated Windows release checks.

The gallery database index and other proposed content-management features are roadmap enhancements. Cancellation is cooperative while an in-process AI calculation runs; the UI reports that it is stopping and keeps the app alive until that step returns. Runtime/dependency-changing releases require the installer instead of mutating a live Python environment. Release notes distinguish tested behavior from service/account/model integrations that were not exercised.
