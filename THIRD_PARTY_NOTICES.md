# Third-Party Notices

AI Influencer Media Grabber is built on open-source software. This file lists the
components that ship with the Windows installer, the optional components the app can
install for you (always after showing a notice), and the separate programs it can talk
to. License texts that must travel with the files are included next to them
(`static/vendor/`, `static/fonts/`, `assets/NODE-LICENSE.txt`); every Python package
also keeps its own license inside `python_runtime/Lib/site-packages/<package>.dist-info/`.

Versions are the ones pinned in `requirements*.txt` for this release.

## Bundled with the installer

### Runtimes

| Component | License | Notes |
|---|---|---|
| Python 3.13 (embeddable distribution) | PSF License 2.0 | https://www.python.org/ |
| pip | MIT | Installed into the private runtime |
| Node.js | MIT (plus bundled third-party licenses) | `node_runtime/node.exe`, used by yt-dlp for YouTube. Full text: `assets/NODE-LICENSE.txt` |
| FFmpeg 7.1 "essentials" build (gyan.dev), shipped inside **imageio-ffmpeg** | **GPL-3.0-or-later** (built with `--enable-gpl --enable-version3`); the imageio-ffmpeg wrapper is BSD-2-Clause | Runs as a separate program. Source: https://ffmpeg.org/download.html and build scripts at https://www.gyan.dev/ffmpeg/builds/ |

### Python packages (core)

| Package | License |
|---|---|
| Flask, Werkzeug, Jinja2, MarkupSafe, itsdangerous, click | BSD-3-Clause |
| blinker | MIT |
| waitress | ZPL-2.1 |
| **yt-dlp**, yt-dlp-ejs | Unlicense (yt-dlp-ejs also includes MIT and ISC parts) |
| **gallery-dl** | **GPL-2.0-only** - runs as a separate process (`python -m gallery_dl`). Source: https://github.com/mikf/gallery-dl |
| mutagen (used by yt-dlp for metadata) | GPL-2.0-or-later. Source: https://github.com/quodlibet/mutagen |
| shazamio, shazamio-core | MIT |
| opencv-python-headless (OpenCV) | Apache-2.0 |
| Pillow | MIT-CMU (HPND) |
| NumPy | BSD-3-Clause |
| imageio-ffmpeg | BSD-2-Clause (bundled FFmpeg: see above) |
| piexif | MIT |
| requests, aiohttp, frozenlist, multidict, propcache, yarl, aiosignal | Apache-2.0 (aiohttp also MIT) |
| urllib3, charset-normalizer, attrs, aiohttp-retry, annotated-types, pydantic, pydantic-core, typing-inspection, brotli | MIT |
| idna, Send2Trash, websockets | BSD-3-Clause |
| aiohappyeyeballs, typing-extensions | PSF-2.0 |
| certifi | MPL-2.0 |
| pycryptodomex | BSD-2-Clause / Public Domain |

### Front-end assets

| Component | License | File |
|---|---|---|
| Tailwind CSS 3.4.17 browser runtime | MIT | `static/vendor/TAILWIND-LICENSE.txt` |
| Font Awesome Free 6.4.0 | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT | `static/vendor/FONTAWESOME-LICENSE.txt` |
| Bangers, Black Han Sans, Lobster, Montserrat, Noto Sans KR, Oswald, Roboto fonts | SIL Open Font License 1.1 | `static/fonts/*-OFL.txt` |

## Optional: AI Engine Pack (installed only after you accept the notice)

The app shows the exact package list, approximate download size, source and license
before installing (`ai_packs.json`). Nothing in the pack is downloaded silently.

| Package | License |
|---|---|
| openai-whisper | MIT |
| stable-ts | MIT |
| PyTorch, torchvision, torchaudio | BSD-3-Clause. The CUDA build includes NVIDIA CUDA runtime libraries under the NVIDIA CUDA Toolkit EULA |
| Hugging Face transformers, tokenizers, huggingface-hub | Apache-2.0 |
| InsightFace (library code) | MIT - **its pretrained models are non-commercial; see Models below** |
| ONNX Runtime (CPU, DirectML, CUDA builds) | MIT |
| onnx | Apache-2.0 |
| SciPy, scikit-image | BSD-3-Clause |
| numba, llvmlite | BSD-2-Clause (llvmlite bundles LLVM: Apache-2.0 with LLVM exception) |
| llama-cpp-python (includes llama.cpp) | MIT |
| keyring | MIT |
| psutil | BSD-3-Clause |
| fal-client, google-genai (GPU pack; opt-in cloud only) | Apache-2.0 |

## Separate programs the app can use

These run as their own processes. The app starts them or talks to them over a local
connection; it does not link to them.

| Program | License | Notes |
|---|---|---|
| Ollama | MIT | Uses an existing install or, with your consent, the official portable build |
| ComfyUI | GPL-3.0 | Optional "Creative engine" with its own Python environment, offered only on capable GPUs |

## Models

AI models are **not** part of the installer or of the AI Engine Pack. Each model is a
separate download, and the app shows its source, size and license **before** you
download it. Models with a non-commercial license carry a "Personal / non-commercial use
only" badge and must be accepted explicitly.

Known non-commercial models (verify the current terms on each model card):

| Model | License |
|---|---|
| InsightFace `inswapper_128` (face swap) and `buffalo_l` (face analysis) | Non-commercial research use only |
| FLUX.1 Kontext [dev] | FLUX.1 [dev] Non-Commercial License |
| CodeFormer (face restoration) | S-Lab License 1.0 (non-commercial) |

GFPGAN (Apache-2.0) is the default face restorer because it allows commercial use. Other
models, such as Whisper (MIT), Qwen3 (Apache-2.0), TranslateGemma (Gemma Terms of Use),
BLIP (BSD-3-Clause), FLUX.1 [schnell] (Apache-2.0) and Wan 2.x (Apache-2.0), show their
license in the app in the same way.

## Online services

Downloads use the public websites you choose (YouTube, TikTok, Instagram and others);
song recognition uses Shazam. Your use of these services is governed by their terms;
see [docs/RESPONSIBLE_USE.md](docs/RESPONSIBLE_USE.md). Cloud AI providers (fal.ai,
Google Gemini) are used only when you add your own key and pick a cloud action.
