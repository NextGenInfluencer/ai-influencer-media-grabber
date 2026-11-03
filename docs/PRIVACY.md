# Privacy

AI Influencer Media Grabber is **local-first**. It runs on your PC, has no account and
sends no analytics or telemetry. This page lists exactly what leaves your computer and
when.

## What stays on your PC

- **Your media, projects and history.** Downloads, caption projects, characters,
  history and settings are stored in your user folder (by default
  `Documents\Media Grabber`). Nothing is uploaded.
- **Lyrics and captions.** Transcription, alignment and translation run locally
  (Whisper, the built-in engine or Ollama on this PC). Lyrics are **never** sent to a
  cloud service unless you explicitly pick a cloud option for that action. The app
  refuses Ollama models or addresses that would route requests off your PC.
- **Cookies.** If you choose Firefox cookies or import a `cookies.txt`, the cookies are
  read or stored only in your local user-data folder. They are sent only to the site
  you are downloading from (that is what makes a logged-in download work), are never
  bundled with the app, never written to logs and never shared with anyone else.
- **Cloud API keys.** Keys for optional cloud providers are stored in **Windows
  Credential Manager** (through the `keyring` library), are always shown masked, and
  are sent only to the provider they belong to.

## When the app connects to the internet

| When | Who it contacts | What is sent |
|---|---|---|
| You download a link | The site of that link (and its media servers) | The link, normal browser-like requests and, if you chose them, your cookies for that site |
| Song recognition (Shazam) | Shazam | A short audio fingerprint of the downloaded track |
| Checking for updates | GitHub (`api.github.com`) | A request for the latest release; no personal data |
| You accept an AI Engine Pack, model or engine download | PyPI, PyTorch, Hugging Face, Ollama or GitHub (shown in the notice) | Normal download requests |
| You choose a cloud AI action | That provider (fal.ai or Google Gemini) | The media and prompt you selected for that action, with your API key |

Nothing is downloaded silently: every AI download first shows its size, source and
license and waits for your consent.

## Local server

The app's interface talks to a server on `127.0.0.1` (your own PC). Requests must carry
a per-session token and come from the app's own pages, so other websites you visit
cannot control it.

## Removing your data

Uninstalling the app keeps your media and projects. To remove everything, delete the
`Documents\Media Grabber` folder, remove downloaded models from **Downloads & Storage**
(or that folder), and delete any saved cloud keys from Windows Credential Manager.
