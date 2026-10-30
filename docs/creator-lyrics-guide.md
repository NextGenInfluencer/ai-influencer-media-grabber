# Lyrics and translations — v3.2.0 guide

See the [completion plan](creator-completion-plan.md) for verification boundaries and environment notes.

## Correct lyrics and karaoke

Start with a video or use **Create from Song** with your audio. Import timed subtitles or transcribe the audio. In **Lyrics & AI**, paste your correct lyrics, including repeated choruses in their actual order.

- **Correct lyrics, keep timing** prepares replacement wording using existing caption timings.
- **Sync lyrics to audio** calculates timing from the audio. Choose a mixed-language option when appropriate, such as Greek + English.
- Review the proposed lines before applying. Flagged timings need listening checks, especially sustained notes, ad-libs, repeated choruses, same-line mixed languages, and words stretched across instrumental breaks (> 4.0 seconds). Resume continues compatible interrupted work.
- **Estimate word timings** divides a line evenly. It does not listen to the song. Use audio alignment for a closer starting point.
- Turn on **Highlight current word** for karaoke. Expand the word timing controls to edit numbers, drag a block or its edges, or nudge a focused block with the arrow keys. Undo restores the previous edit.

An ordinary SRT supplies line timings, not word timings. Its presence alone cannot make word highlighting accurate.

## Add a translation

Choose the translation language under **Text layout & bilingual captions**. In **Translation workspace**, either enter and approve a translation for the selected line or choose an installed local model and generate a proposal.

Use **Song context** for the speaker, story and emotional meaning. Use **Glossary** for names, slang and preferred wording. Review the proposed translations before applying: the model can misunderstand metaphors or tense. Exact repeated lines reuse wording. Lock accepted lines to protect them from later AI translation.

Original lyrics remain separate. Changing original words marks their translation as needing review. Translation-only export requires approved translations for every line. Both-language display includes approved translations and can hide identical originals/translations.

For optional Ollama translation, Stop is checked as response chunks arrive. A silent connection can take up to its 30-second read timeout to return. If the model takes too long to load, load it in Ollama first and retry. Interrupted responses do not replace accepted lyrics or translations; bounded NDJSON streaming and mid-stream cancellation have been verified against a local loopback server, while live Ollama daemon inference depends on having Ollama installed on the host.

The local translation integration supports Qwen3 and installed Ollama models. It does not send lyrics to a cloud service. For Qwen3, install the **AI Engine Pack** from the main Studio and restart, open a caption project, then choose **Set up local translator (2.5 GB)** in the translation workspace. Keep at least 2.8 GB free on the app drive. Setup downloads the pinned [official Qwen model](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf), verifies its SHA-256 checksum, then selects it for this project. Existing model files are checked without being replaced. Stop cancels the download; a retry starts again. An interrupted download is never offered as an installed model. Manual translation does not need an AI model.

## Style and export

AI Pack setup verifies that its libraries can load before reporting success. Restart after installing. A missing DLL or failed import is shown as an installation failure, rather than leaving enabled controls that cannot run. The default packaged translation runtime (`llama-cpp-python` prebuilt wheel) runs on CPU (`llama_supports_gpu_offload() == False`), while FFmpeg video exports automatically use hardware encoding (`h264_nvenc` / QSV / AMF) when available with CPU fallback.

Setup first prepares the build tools needed by the embedded Python runtime, then installs the AI packages while preserving the core dependency constraints. Both clean combined AI installation and full Windows Inno Setup fresh/upgrade (`3.1.5 -> 3.2.0`) installation have been verified in isolated directories. Because `3.2.0` updates dependency constraints, upgrading from `3.1.5` requires the full release installer rather than source-only OTA staging.

Adjust line spacing, text width, letter spacing, original–translation gap, position and background styling. Choose **Selected line** for a local style override or **All lines** for the base style. Manual line breaks preserve word timings when the words themselves stay the same.

With shared layout enabled, a word or unspaced phrase that is wider than the text box is reduced in size, including its letter spacing. Its spelling and timing stay unchanged. Widen the box or edit the line if the fitted text becomes too small to read. Excessive padding that leaves no room for text produces a message asking you to reduce padding or widen the box.

If the chosen decorative font lacks a letter (or only includes isolated Greek math symbols without full modern Greek tonos support), shared layout falls back to bundled Roboto for Greek and Noto Sans KR for Korean. The substituted letters are measured with that font, and the same choice is included in preview and ASS/MP4 output. The decorative font remains on supported letters. Unusual symbols outside these fonts can still require a suitable custom font.

Use **5s Check** before exporting a full video. SRT contains text and line times; it does not preserve fonts, karaoke styling or backgrounds. Styled ASS preserves supported styling; MP4 burns the appearance into the video.

## Pending uploads

Pending composition uploads are stored per project in this browser, up to 512 MB per draft. They survive reopening settings, changing projects and reloading once stored. Large drafts or browser storage errors must be resolved before switching projects. Apply the composition to save the prepared media in the project. Clearing browser storage also clears browser-only drafts.

Submitting a composition keeps its settings and uploads available until rendering succeeds. If rendering fails, retry with the retained draft. A successful full composition render clears consumed uploads; applying only the clip sequence keeps unapplied audio and canvas settings.
