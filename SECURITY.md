# Security Policy & Release Verification

AI Influencer Media Grabber is a **100% open-source, local-first Windows desktop application**. Every line of Python and JavaScript shipped inside the Windows installer matches this repository, and the app operates without telemetry, analytics, or silent background downloads.

---

## 1. Verifying Your Download (`v5.0.15`)

Before or after running **`AI-Influencer-Media-Grabber-v5.0.15-Setup.exe`**, you can verify its cryptographic checksum and independent antivirus scan results:

| Field | Value |
|---|---|
| **Installer Filename** | `AI-Influencer-Media-Grabber-v5.0.15-Setup.exe` |
| **Exact Size** | `119,009,012` bytes (`113.5 MB`) |
| **SHA-256 Checksum** | `5fe71dbc60879fcdaccde3f77e6518fc8ac2ca3353de2aca3c0391d975617ebf` |
| **Checksum File** | [`SHA256SUMS-v5.0.15.txt`](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/releases/download/v5.0.15/SHA256SUMS-v5.0.15.txt) |
| **Microsoft Defender Scan** | **0 threats found** (`MpCmdRun.exe -Scan -ScanType 3`) |
| **Previous `v5.0.14` VirusTotal Report** | [View VirusTotal Analysis (`6dc91907...c02a6`)](https://www.virustotal.com/gui/file/6dc91907d5de1d0d90ecd4ab6c57d48cfc7b710d54a6a7093c248005d74c02a6) |
| **Windows Privileges** | **Standard User (`PrivilegesRequired=lowest`)** — never requests Administrator (UAC) elevation |

### Verify in Windows PowerShell (1 command)
Open PowerShell in your `Downloads` folder and run:
```powershell
Get-FileHash .\AI-Influencer-Media-Grabber-v5.0.15-Setup.exe -Algorithm SHA256
```
Confirm the output matches:
```text
5FE71DBC60879FCDACCDE3F77E6518FC8AC2CA3353DE2ACA3C0391D975617EBF
```

### Why does Windows SmartScreen show "Windows protected your PC"?
Because this is a free, open-source project and the installer is not signed with a paid commercial EV/OV code-signing certificate, Windows SmartScreen displays its standard *"Unknown publisher"* prompt on first download.
- You can verify the SHA-256 hash above and inspect the [VirusTotal report](https://www.virustotal.com/gui/file/6dc91907d5de1d0d90ecd4ab6c57d48cfc7b710d54a6a7093c248005d74c02a6), then click **More info → Run anyway**.
- The installer runs strictly with **lowest user privileges** (`PrivilegesRequired=lowest` in [`installer.iss`](installer.iss)) and installs only into your user profile folder (`%LOCALAPPDATA%\AI Influencer Media Grabber`).

---

## 2. Built-In Security & Privacy Guarantees

1. **Localhost-Only Server (`127.0.0.1`)**:
   - The local UI server binds strictly to `127.0.0.1` (loopback), never `0.0.0.0`. No other computer or device on your local network can access it.
2. **Per-Session CSRF & Origin Protection**:
   - Every browser session is issued a cryptographic `X-Media-Token` (and checked for local `Origin`/`Referer` headers) on state-changing and sensitive API routes in [`app_local.py`](app_local.py), preventing external websites open in your browser from invoking local API actions.
3. **Filesystem Containment & Path Safety**:
   - Media serving, previewing, subtitle burning, and file operations validate paths through [`media_safety.py`](media_safety.py) (`contained_path`), blocking `..` path traversal and symlink escapes.
   - Deleted gallery files are sent to the **Windows Recycle Bin** (`send2trash`) rather than permanently erased.
4. **No Silent Downloads & Pinned SHA-256 Verification**:
   - The installer ships with **zero AI models**. Nothing AI-related downloads until you review its size, source, and license in **Set up AI** and click Install.
   - All bundled runtimes ([`build_staging.py`](build_staging.py)) and catalog AI models ([`ai_core/catalog.json`](ai_core/catalog.json), [`ai_core/models.py`](ai_core/models.py)) are verified against pinned SHA-256 hashes before use.
5. **Safe In-App Updates & Rollback**:
   - OTA updates ([`safe_update.py`](safe_update.py)) validate every Python file with `ast.parse`, reject path traversal and symlinks, refuse dependency changes without the full installer, back up modified and retired files to `.updates/backup-*`, and automatically roll back on failure.
   - In-app download engine updates ([`download_support.py`](download_support.py)) allow only `yt-dlp` and `gallery-dl` (`--only-binary :all: --no-deps`), run a dry verification check in an isolated subprocess, and roll back to the previous pinned versions on failure.
   - User media, `history.json`, cookies, settings, custom fonts, models, and caption projects are strictly protected and never overwritten or deleted during updates.
6. **Credentials & Privacy**:
   - Optional cloud API keys (FAL, Google Gemini) are stored in the **Windows Credential Manager** via `keyring` ([`ai_core/cloud.py`](ai_core/cloud.py)), never in plain-text config files.
   - Song lyrics and captions never leave your PC unless you explicitly invoke an opt-in cloud action and accept its cost confirmation. See [`docs/PRIVACY.md`](docs/PRIVACY.md).

---

## 3. Reporting a Security Issue

If you discover a security or privacy issue, please open a report on the [GitHub Issues page](https://github.com/NextGenInfluencer/ai-influencer-media-grabber/issues) (or use GitHub's private vulnerability reporting if enabled on the repository) with steps to reproduce.
