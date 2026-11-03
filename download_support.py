"""Downloader support: login sessions, Instagram posts/profiles, gallery-dl fallbacks, storage helpers.

Rules this module follows:
* Downloaded media is stored byte-exact. Derived copies (``normalized_copy``) live outside the library.
* Instagram is asked once per post (single extraction); login walls fail fast with one clear message.
* A download only succeeds when files were actually created by this run.
* Session choices are platform-aware and every cookies.txt use resolves to one absolute stored path.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

import requests
import yt_dlp
import yt_dlp.extractor.instagram

import job_process as subprocess
from media_safety import MEDIA_EXTENSIONS, safe_media_name

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Referer': 'https://www.instagram.com/'
}

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'}
DEFAULT_IG_VIDEO_FORMAT = 'bv*+ba/b'
PROFILE_LISTING_RANGE = '1-48'
_RESERVED_IG_PATHS = {'p', 'reel', 'reels', 'stories', 'tv', 'explore', 'direct', 'accounts', 'api',
                      'graphql', 'about', 'developer', 'share'}
_IG_POST_SEGMENTS = {'p', 'reel', 'reels', 'tv'}
_LOGIN_MARKERS = (
    'login required', 'login_required', 'redirect to login', 'accounts/login', 'not logged in',
    '--cookies', 'rate-limit reached', 'checkpoint_required', 'challenge page', '401 unauthorized',
    'authorizationerror', 'authenticationerror', 'locked behind the login', 'this account is private',
)
_CHROMIUM_COOKIE_MARKERS = ('could not copy chrome cookie database', 'failed to decrypt with dpapi',
                            'app-bound', 'database is locked', 'failed to decrypt cookie')
_PLATFORM_FOLDERS = (
    (('youtube.com', 'youtu.be', 'youtube-nocookie.com'), 'YouTube'),
    (('instagram.com', 'instagr.am'), 'Instagram'),
    (('tiktok.com',), 'TikTok'),
    (('twitter.com', 'x.com'), 'Twitter'),
)


# --- Login sessions (cookies) --------------------------------------------------------------
# The imported cookies.txt lives in the user-data folder under cookies/cookies.txt. Its contents are
# never logged or returned by any endpoint; only aggregate metadata (domain count, age) is exposed.

MAX_COOKIE_FILE_BYTES = 2 * 1024 * 1024
NETSCAPE_HEADER = '# Netscape HTTP Cookie File'
_COOKIE_FILE_HEADERS = ('# Netscape HTTP Cookie File', '# HTTP Cookie File')
_HTTPONLY_PREFIX = '#HttpOnly_'
APP_DIR = Path(__file__).resolve().parent

ANONYMOUS = 'none'
COOKIES_FILE = 'cookies.txt'
CHROMIUM_WINDOWS_NOTE = ("Chrome/Edge use App-Bound Encryption on Windows: export cookies.txt with the "
                         "'Get cookies.txt LOCALLY' extension, then Import.")


class CookieError(ValueError):
    """Raised when a login-session choice cannot be used; the message is user-facing."""


def data_dir() -> Path:
    """User-data root shared with the rest of the app (honours MEDIA_GRABBER_DATA_DIR)."""
    configured = os.environ.get('MEDIA_GRABBER_DATA_DIR')
    return Path(configured) if configured else Path.home() / 'Documents' / 'Media Grabber'


def stored_cookie_path() -> Path:
    return data_dir() / 'cookies' / COOKIES_FILE


def browser_options(platform: str | None = None) -> dict:
    """Session choices that actually work on the given platform (defaults to ``sys.platform``)."""
    platform = platform or sys.platform
    anonymous = {'value': ANONYMOUS, 'label': 'Anonymous (public posts)'}
    imported = {'value': COOKIES_FILE, 'label': 'Import cookies.txt…'}
    if platform == 'win32':
        options = [anonymous, {'value': 'firefox', 'label': 'Firefox (recommended)'}, imported]
        note = CHROMIUM_WINDOWS_NOTE
    else:
        browsers = [('chrome', 'Chrome'), ('firefox', 'Firefox'), ('edge', 'Edge')]
        if platform == 'darwin':
            browsers.append(('safari', 'Safari'))
        options = [anonymous, *({'value': value, 'label': f'{label} profile'} for value, label in browsers), imported]
        note = ''
    return {'platform': platform, 'options': options, 'note': note}


def _allowed_browsers(platform: str | None = None) -> set[str]:
    return {option['value'] for option in browser_options(platform)['options']} - {ANONYMOUS, COOKIES_FILE}


def cookie_options(browser: str | None, platform: str | None = None) -> tuple[dict, list[str]]:
    """Translate a session choice into a yt-dlp options patch and gallery-dl CLI arguments.

    Every cookies.txt reference resolves to the single absolute stored path.
    """
    choice = (browser or ANONYMOUS).strip().lower()
    if choice in {ANONYMOUS, ''}:
        return {}, []
    if choice == COOKIES_FILE:
        migrate_legacy_cookies()
        path = stored_cookie_path()
        if not path.is_file():
            raise CookieError('No cookies.txt imported yet. Choose "Import cookies.txt…" and select your exported file.')
        return {'cookiefile': str(path)}, ['--cookies', str(path)]
    if choice in _allowed_browsers(platform):
        return {'cookiesfrombrowser': (choice, None, None, None)}, ['--cookies-from-browser', choice]
    if choice in {'chrome', 'edge', 'brave', 'chromium', 'opera', 'vivaldi'}:
        raise CookieError(CHROMIUM_WINDOWS_NOTE)
    raise CookieError(f'"{browser}" is not available on this computer. Choose Anonymous, Firefox or Import cookies.txt.')


def _cookie_domain(line: str) -> str | None:
    """Return the cookie domain of a valid Netscape data line, else None."""
    if line.startswith(_HTTPONLY_PREFIX):
        line = line[len(_HTTPONLY_PREFIX):]
    fields = line.split('\t')
    if len(fields) != 7:
        return None
    domain, subdomains, path, secure, expiry, name, _value = fields
    if not domain or not name or not path.startswith('/'):
        return None
    if subdomains.upper() not in {'TRUE', 'FALSE'} or secure.upper() not in {'TRUE', 'FALSE'}:
        return None
    if not expiry.lstrip('-').isdigit():
        return None
    return domain.lstrip('.').lower()


def parse_cookie_text(text: str) -> dict:
    """Validate Netscape cookies.txt content; returns counts only (never values)."""
    lines = text.lstrip('\ufeff').splitlines()
    has_header = bool(lines) and lines[0].strip().startswith(_COOKIE_FILE_HEADERS)
    domains: set[str] = set()
    cookies = invalid = 0
    for raw in lines:
        line = raw.rstrip('\r\n')
        if not line.strip() or (line.startswith('#') and not line.startswith(_HTTPONLY_PREFIX)):
            continue
        domain = _cookie_domain(line)
        if domain is None:
            invalid += 1
            continue
        cookies += 1
        domains.add(domain)
    if cookies == 0:
        raise CookieError('This is not a Netscape cookies.txt file (no tab-separated cookie lines found). '
                          "Export it with the 'Get cookies.txt LOCALLY' extension.")
    return {'has_header': has_header, 'cookies': cookies, 'domains': sorted(domains), 'invalid_lines': invalid}


def import_cookie_bytes(raw: bytes) -> dict:
    """Validate and store an uploaded cookies.txt atomically. Returns status metadata."""
    if not raw:
        raise CookieError('The selected file is empty.')
    if len(raw) > MAX_COOKIE_FILE_BYTES:
        raise CookieError('cookies.txt is larger than 2 MB. Export only the sites you need.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise CookieError('cookies.txt must be a UTF-8 text file.') from exc
    parse_cookie_text(text)
    body = text.replace('\r\n', '\n').replace('\r', '\n')
    if not body.lstrip().startswith(_COOKIE_FILE_HEADERS):
        body = f'{NETSCAPE_HEADER}\n{body}'
    _write_private(stored_cookie_path(), body)
    return cookie_status()


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.cookies-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
        if os.name != 'nt':
            os.chmod(tmp, 0o600)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def cookie_status(now: float | None = None) -> dict:
    """Metadata about the stored cookies.txt; contains no cookie names or values."""
    migrate_legacy_cookies()
    path = stored_cookie_path()
    if not path.is_file():
        return {'exists': False}
    modified = path.stat().st_mtime
    try:
        summary = parse_cookie_text(path.read_text(encoding='utf-8', errors='replace'))
    except CookieError:
        return {'exists': True, 'valid': False, 'modified': modified, 'age_days': _age_days(modified, now),
                'domains': 0, 'cookies': 0, 'has_instagram': False}
    domains = summary['domains']
    return {
        'exists': True,
        'valid': True,
        'modified': modified,
        'age_days': _age_days(modified, now),
        'domains': len(domains),
        'cookies': summary['cookies'],
        'has_instagram': any(d == 'instagram.com' or d.endswith('.instagram.com') for d in domains),
    }


def _age_days(modified: float, now: float | None) -> int:
    return max(0, int(((now or time.time()) - modified) // 86400))


def delete_cookies() -> bool:
    path = stored_cookie_path()
    if path.is_file():
        path.unlink()
        return True
    return False


def migrate_legacy_cookies() -> bool:
    """Copy a legacy app-folder cookies.txt into user data once; the original is left untouched."""
    target = stored_cookie_path()
    legacy = APP_DIR / COOKIES_FILE
    if target.exists() or not legacy.is_file():
        return False
    try:
        parse_cookie_text(legacy.read_text(encoding='utf-8-sig', errors='replace'))
    except (CookieError, OSError):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
    return True


class LoginRequiredError(RuntimeError):
    """The site refused anonymous access; the user must choose Firefox or import cookies.txt."""

    def __init__(self, site: str = 'Instagram'):
        super().__init__(f'{site} requires login → choose Firefox or import cookies.txt')
        self.site = site


class InstagramMediaIE(yt_dlp.extractor.instagram.InstagramIE):
    """Instagram extractor that permits extraction of image-only posts and carousels."""
    def raise_no_formats(self, msg, expected=False):
        pass


# --- URL classification -------------------------------------------------------------------

def url_hostname(url: str) -> str:
    try:
        host = urllib.parse.urlsplit((url or '').strip()).hostname or ''
    except ValueError:
        return ''
    return host.lower().rstrip('.')


def host_matches(url: str, *domains: str) -> bool:
    """True when the URL's hostname is one of ``domains`` or a subdomain of one."""
    host = url_hostname(url)
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def platform_folder(url: str) -> str:
    for domains, folder in _PLATFORM_FOLDERS:
        if host_matches(url, *domains):
            return folder
    return 'Other'


def is_instagram_url(url: str) -> bool:
    return bool(url) and (url.strip().startswith('@') or host_matches(url, 'instagram.com', 'instagr.am'))


def wants_playlist(url: str) -> bool:
    """Only a YouTube playlist page (``list=`` without ``v=``) downloads as a playlist."""
    if not host_matches(url, 'youtube.com', 'youtu.be', 'youtube-nocookie.com'):
        return False
    parts = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qs(parts.query)
    return 'list' in query and 'v' not in query and not host_matches(url, 'youtu.be')


def is_instagram_profile_url(url: str) -> bool:
    """True for a user profile (or one of its tabs); False for posts like ``/<user>/p/<code>``."""
    if not url:
        return False
    clean = url.strip()
    if clean.startswith('@'):
        return True
    if not host_matches(clean, 'instagram.com'):
        return False
    parts = [p for p in urllib.parse.urlsplit(clean).path.split('/') if p]
    if not parts or parts[0].lower() in _RESERVED_IG_PATHS:
        return False
    if len(parts) >= 3 and parts[1].lower() in _IG_POST_SEGMENTS:
        return False
    return True


def extract_instagram_username(url: str) -> str:
    """Extract clean username from an Instagram profile URL or handle."""
    clean = url.strip()
    if clean.startswith('@'):
        return clean.lstrip('@')
    parts = [p for p in urllib.parse.urlsplit(clean).path.split('/') if p]
    return parts[0] if parts else 'Instagram Creator'


# --- Error translation -----------------------------------------------------------------------

def is_login_error(message: str) -> bool:
    text = (message or '').lower()
    return any(marker in text for marker in _LOGIN_MARKERS)


def friendly_download_error(message: str, url: str = '') -> str:
    """Map raw yt-dlp/gallery-dl failures to one actionable sentence."""
    text = (message or '').lower()
    if any(marker in text for marker in _CHROMIUM_COOKIE_MARKERS):
        return CHROMIUM_WINDOWS_NOTE
    if 'could not find firefox' in text or 'firefox cookies database' in text:
        return 'Firefox cookies were not found. Sign in to the site in Firefox, or import cookies.txt.'
    if is_instagram_url(url) and is_login_error(message):
        return str(LoginRequiredError())
    return message


def _uses_login_session(browser: str | None) -> bool:
    return bool(browser) and browser != 'none'


def _session_args(browser: str | None) -> tuple[dict, list[str]]:
    try:
        return cookie_options(browser)
    except CookieError as exc:
        raise RuntimeError(str(exc)) from exc


# --- gallery-dl helpers ---------------------------------------------------------------------

def _gallery_dl(*args: str) -> list[str]:
    return [sys.executable, '-m', 'gallery_dl', *args]


def parse_gallery_dl_listing(output: str, username: str) -> tuple[list[dict], str, list[str]]:
    """Parse ``gallery-dl --dump-json`` output into picker posts, an avatar URL and error messages."""
    try:
        messages = json.loads(output) if output and output.strip() else []
    except ValueError:
        return [], '', ['gallery-dl returned unreadable data']
    posts: dict[str, dict] = {}
    avatar = ''
    errors: list[str] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, list) or not message:
            continue
        kind = message[0]
        if kind == -1 and len(message) > 1 and isinstance(message[1], dict):
            errors.append(str(message[1].get('message') or message[1].get('error') or 'Unknown error'))
            continue
        if kind == 2 and len(message) > 1:
            meta, file_url = message[1], ''
        elif kind == 3 and len(message) > 2:
            meta, file_url = message[2], str(message[1])
        else:
            continue
        if not isinstance(meta, dict):
            continue
        code = meta.get('post_shortcode') or meta.get('shortcode')
        if not code:
            continue
        post = posts.setdefault(code, {
            'id': code,
            'url': meta.get('post_url') or f'https://www.instagram.com/p/{code}/',
            'title': '',
            'thumbnail': '',
            'type': 'photo',
            'count': 0,
        })
        description = str(meta.get('description') or '').strip()
        if description and not post['title']:
            post['title'] = description.splitlines()[0][:120]
        if kind == 2:
            post['count'] = int(meta.get('count') or post['count'] or 0)
            if meta.get('type') == 'reel':
                post['type'] = 'video'
            user = meta.get('user') if isinstance(meta.get('user'), dict) else {}
            avatar = avatar or user.get('profile_pic_url_hd') or user.get('profile_pic_url') or ''
        else:
            if not post['thumbnail']:
                post['thumbnail'] = meta.get('display_url') or ('' if meta.get('video_url') else file_url)
            extension = '.' + str(meta.get('extension') or '').lower()
            if meta.get('video_url') or extension in VIDEO_EXTENSIONS:
                post['type'] = 'video'
    for post in posts.values():
        post['title'] = post['title'] or f'Post by @{username}'
    return list(posts.values()), avatar, errors


def extract_instagram_profile(url: str, browser=None) -> dict:
    """List recent posts of a profile for the picker using gallery-dl (no files are downloaded)."""
    username = extract_instagram_username(url)
    _, session_args = _session_args(browser)
    command = _gallery_dl('--dump-json', '--post-range', PROFILE_LISTING_RANGE, *session_args,
                          f'https://www.instagram.com/{username}/posts/')
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    posts, avatar, errors = parse_gallery_dl_listing(result.stdout or '', username)
    problems = ' '.join(errors + [result.stderr or ''])
    if not posts and (is_login_error(problems) or (errors and not _uses_login_session(browser))):
        raise LoginRequiredError()
    if not posts and errors:
        raise RuntimeError(f'Could not list @{username}: {errors[0]}')
    return {
        'is_profile': True,
        'platform': 'instagram',
        'username': username,
        'title': f'Instagram Profile: @{username}',
        'uploader': username,
        'thumbnail': avatar or (posts[0]['thumbnail'] if posts else ''),
        'duration': 0,
        'post_count': len(posts),
        'posts': posts,
    }


def snapshot_media(folder: Path) -> dict[str, tuple[float, int]]:
    """Media files currently present under ``folder`` keyed by path, with (mtime, size)."""
    folder = Path(folder)
    if not folder.exists():
        return {}
    snapshot = {}
    for file in folder.rglob('*'):
        if file.is_file() and file.suffix.lower() in MEDIA_EXTENSIONS:
            stat = file.stat()
            snapshot[str(file)] = (stat.st_mtime, stat.st_size)
    return snapshot


def new_media_files(folder: Path, before: dict[str, tuple[float, int]]) -> list[Path]:
    """Files created or rewritten since ``before`` was taken (gallery-dl may backdate mtimes)."""
    after = snapshot_media(folder)
    return sorted(Path(path) for path, stamp in after.items() if before.get(path) != stamp)


def _run_gallery_dl(command: list[str], report: Callable[[dict], Any]) -> tuple[int, list[str], int]:
    """Run gallery-dl streaming its log; returns (exit code, output lines, skipped-file count)."""
    lines: list[str] = []
    skipped = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace') as process:
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            lines.append(line)
            if line.startswith('# '):
                skipped += 1
            report({'status': 'gallery-dl: ' + line[-150:]})
        code = process.wait()
    subprocess.check_cancelled()
    return code, lines, skipped


def _entries_for(files: Iterable[Path], url: str, extractor_key: str, uploader: str | None = None) -> list[dict]:
    entries = []
    for file in files:
        entry = {'filepath': str(file), '_filename': str(file), 'title': file.stem,
                 'webpage_url': url, 'extractor_key': extractor_key}
        if uploader:
            entry['uploader'] = uploader
        entries.append(entry)
    return entries


# --- Instagram posts --------------------------------------------------------------------------

def _instagram_extract(url: str, browser) -> dict:
    """One metadata request for a post/reel/carousel, tolerant of photo-only posts."""
    ydl_patch, _ = _session_args(browser)
    opts = {'quiet': True, 'no_warnings': True, **ydl_patch}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.add_info_extractor(InstagramMediaIE())
            info = ydl.extract_info(url, download=False, process=False, ie_key=InstagramMediaIE.ie_key())
    except yt_dlp.utils.DownloadError as exc:
        if is_login_error(str(exc)):
            raise LoginRequiredError() from exc
        raise
    return info


def _post_entries(info: dict) -> list[dict]:
    entries = info.get('entries') if info.get('_type') == 'playlist' else [info]
    return [entry for entry in (entries or []) if isinstance(entry, dict)]


def extract_instagram_preview(url, browser=None):
    """Extract metadata for UI preview without requiring video formats."""
    if is_instagram_profile_url(url):
        return extract_instagram_profile(url, browser=browser)
    info = _instagram_extract(url, browser)
    if not info:
        return None
    entries = _post_entries(info)
    first_entry = entries[0] if entries else info
    uploader = info.get('uploader') or info.get('channel') or first_entry.get('uploader') or 'Instagram Creator'
    title = info.get('title') or first_entry.get('title') or f"Post by {uploader}"
    thumbs = first_entry.get('thumbnails') or info.get('thumbnails') or []
    return {
        'title': title,
        'uploader': uploader,
        'thumbnail': thumbs[-1].get('url', '') if thumbs else '',
        'duration': first_entry.get('duration') or 0
    }


def _has_video(entry: dict) -> bool:
    return any(f.get('url') and f.get('vcodec') != 'none' for f in entry.get('formats') or [])


def _unique_stem(directory: Path, stem: str) -> str:
    candidate, counter = stem, 1
    while any(directory.glob(glob_escape(candidate) + '.*')):
        candidate = f'{stem} ({counter})'
        counter += 1
    return candidate


def glob_escape(text: str) -> str:
    return ''.join(f'[{ch}]' if ch in '[]*?' else ch for ch in text)


def _download_video_entry(entry: dict, url: str, browser, stem_path: Path, download_opts: dict | None) -> Path:
    """Download one video slide through yt-dlp so video and audio streams are merged."""
    ydl_patch, _ = _session_args(browser)
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': DEFAULT_IG_VIDEO_FORMAT,
        'merge_output_format': 'mp4',
        **(download_opts or {}),
        **ydl_patch,
        'outtmpl': str(stem_path) + '.%(ext)s',
        'noplaylist': True,
    }
    entry = dict(entry)
    entry.setdefault('webpage_url', url)
    entry.setdefault('extractor', 'Instagram')
    entry.setdefault('extractor_key', 'Instagram')
    entry.pop('_type', None)
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.process_ie_result(entry, download=True) or {}
    for item in result.get('requested_downloads') or []:
        if item.get('filepath') and os.path.isfile(item['filepath']):
            return Path(item['filepath'])
    for candidate in sorted(stem_path.parent.glob(glob_escape(stem_path.name) + '.*')):
        if candidate.suffix.lower() in VIDEO_EXTENSIONS | {'.mp3', '.m4a'}:
            return candidate
    raise RuntimeError('Video download finished without producing a file')


def _download_image(media_url: str, dest_file: Path) -> None:
    """Stream an image byte-for-byte; the original is never re-encoded or cropped."""
    resp = requests.get(media_url, headers=_HEADERS, stream=True, timeout=45)
    resp.raise_for_status()
    partial = dest_file.with_name(dest_file.name + '.part')
    try:
        with open(partial, 'wb') as handle:
            for chunk in resp.iter_content(chunk_size=65536):
                subprocess.check_cancelled()
                if chunk:
                    handle.write(chunk)
        os.replace(partial, dest_file)
    finally:
        if partial.exists():
            partial.unlink()


def _image_extension(media_url: str) -> str:
    suffix = Path(urllib.parse.urlsplit(media_url).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else '.jpg'


def instagram_download(url, output_path, browser, report, custom_name=None, download_opts=None):
    """Download every slide of an Instagram post/reel/carousel from a single extraction."""
    report({'status': 'Fetching Instagram post details...'})
    info = _instagram_extract(url, browser)
    if not info:
        raise RuntimeError('Could not extract Instagram post data')
    entries = _post_entries(info)
    if not entries:
        raise RuntimeError('No media entries found in Instagram post')

    raw_uploader = info.get('uploader') or info.get('channel') or entries[0].get('uploader') or 'Instagram'
    safe_uploader = safe_media_name(raw_uploader).rsplit('.', 1)[0] or 'Instagram'
    target_dir = Path(output_path) / safe_uploader
    target_dir.mkdir(parents=True, exist_ok=True)

    total = len(entries)
    downloaded_entries = []
    for idx, entry in enumerate(entries, 1):
        subprocess.check_cancelled()
        entry_id = str(entry.get('id') or f"slide_{idx}")
        raw_title = custom_name or entry.get('title') or info.get('title') or f"Post by {safe_uploader}"
        is_video = _has_video(entry)
        if not is_video and raw_title.startswith('Video by '):
            raw_title = 'Photo by ' + raw_title[9:]
        clean_title = safe_media_name(raw_title).rsplit('.', 1)[0]
        base_name = f"{idx:02d} - {clean_title}_{entry_id}" if total > 1 else f"{clean_title}_{entry_id}"
        stem = _unique_stem(target_dir, base_name)
        prefix = f"[{idx}/{total}] " if total > 1 else ""

        if is_video:
            report({'status': f"{prefix}Downloading slide {idx}/{total} (VIDEO)..."})
            dest_file = _download_video_entry(entry, url, browser, target_dir / stem, download_opts)
        else:
            thumbs = entry.get('thumbnails') or []
            if not thumbs or not thumbs[-1].get('url'):
                continue
            media_url = thumbs[-1]['url']
            ext = _image_extension(media_url)
            report({'status': f"{prefix}Downloading slide {idx}/{total} ({ext[1:].upper()})..."})
            dest_file = target_dir / f"{stem}{ext}"
            _download_image(media_url, dest_file)

        downloaded_entries.append({
            'filepath': str(dest_file),
            '_filename': str(dest_file),
            'title': raw_title,
            'uploader': raw_uploader,
            'webpage_url': url,
            'extractor_key': 'Instagram',
            'description': info.get('description') or entry.get('description') or '',
        })

    if not downloaded_entries:
        raise RuntimeError('No media files could be downloaded from this Instagram post')
    return {'_type': 'playlist', 'entries': downloaded_entries}


# --- Instagram profiles -----------------------------------------------------------------------

def instagram_profile_download(url, output_path, browser, report, mode='all', selected_urls=None,
                               custom_name=None, download_opts=None):
    """Download a profile: chosen posts one by one, or the whole feed (all/photos/videos) via gallery-dl."""
    username = extract_instagram_username(url)
    safe_uploader = safe_media_name(username).rsplit('.', 1)[0] or 'Instagram'
    target_dir = Path(output_path) / safe_uploader
    target_dir.mkdir(parents=True, exist_ok=True)

    chosen = [u for u in (selected_urls or []) if isinstance(u, str) and u.startswith(('http://', 'https://'))]
    if chosen:
        return _download_selected_posts(chosen, username, output_path, browser, report, custom_name, download_opts)

    _, session_args = _session_args(browser)
    command = _gallery_dl('-D', str(target_dir), *session_args)
    if mode == 'photos':
        command.extend(['--filter', "extension in ('jpg', 'jpeg', 'png', 'webp', 'heic')"])
    elif mode == 'videos':
        command.extend(['--filter', "extension in ('mp4', 'mov', 'webm', 'm4v')"])
    command.append(f"https://www.instagram.com/{username}/posts/")

    report({'status': f"Downloading @{username} via gallery-dl ({mode})..."})
    before = snapshot_media(target_dir)
    code, lines, skipped = _run_gallery_dl(command, report)
    created = new_media_files(target_dir, before)
    if not created:
        log = ' '.join(lines[-20:])
        if is_login_error(log) or (code != 0 and not _uses_login_session(browser)):
            raise LoginRequiredError()
        if code != 0:
            raise RuntimeError(f"gallery-dl could not download @{username} (exit code {code}); see activity log")
        if skipped:
            raise RuntimeError(f"Nothing new to download: all {skipped} files from @{username} are already in your library")
        raise RuntimeError(f"No media were saved from @{username} (no matching public posts)")
    if code != 0:
        report({'status': f"gallery-dl reported errors (exit code {code}); {len(created)} new file(s) were saved"})
    return {'_type': 'playlist', 'entries': _entries_for(created, url, 'Instagram', username)}


def _download_selected_posts(urls, username, output_path, browser, report, custom_name, download_opts):
    total = len(urls)
    report({'status': f"Downloading {total} selected posts from @{username}..."})
    downloaded, failed = [], 0
    for index, post_url in enumerate(urls, 1):
        subprocess.check_cancelled()
        report({'status': f"[{index}/{total}] Downloading post..."})
        try:
            result = instagram_download(post_url, output_path, browser, report,
                                        custom_name=custom_name, download_opts=download_opts)
            downloaded.extend(result.get('entries') or [])
        except LoginRequiredError:
            raise
        except Exception as exc:
            if 'cancelled' in str(exc).lower():
                raise
            failed += 1
            report({'status': f"Skipping post {index}: {exc}"})
    if not downloaded:
        raise RuntimeError(f"No posts could be downloaded from @{username}")
    return {'_type': 'playlist', 'entries': downloaded, 'failed_items': failed}


# --- Generic gallery fallback -----------------------------------------------------------------

def gallery_download(url, output_path, browser, report, custom_name=None, profile_mode='all',
                     selected_urls=None, download_opts=None):
    """Instagram posts/profiles natively; anything else through gallery-dl into a fresh folder."""
    if is_instagram_url(url):
        if is_instagram_profile_url(url):
            return instagram_profile_download(url, output_path, browser, report, mode=profile_mode,
                                              selected_urls=selected_urls, custom_name=custom_name,
                                              download_opts=download_opts)
        try:
            return instagram_download(url, output_path, browser, report, custom_name=custom_name,
                                      download_opts=download_opts)
        except LoginRequiredError:
            raise
        except Exception as exc:
            message = str(exc)
            if 'cancelled' in message.lower():
                raise
            if is_login_error(message):
                raise LoginRequiredError() from exc
            report({'status': f'Native Instagram download failed ({message[:200]}); trying gallery-dl...'})

    _, session_args = _session_args(browser)
    folder = Path(output_path) / ('Gallery-' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    try:
        code, lines, _ = _run_gallery_dl(_gallery_dl('-D', str(folder), *session_args, url), report)
        created = new_media_files(folder, {})
        if code != 0 and not created:
            if is_instagram_url(url) and is_login_error(' '.join(lines[-20:])):
                raise LoginRequiredError()
            raise RuntimeError('Gallery download failed; see activity log')
        if not created:
            raise RuntimeError('No media files were downloaded')
        return {'_type': 'playlist', 'entries': _entries_for(created, url, platform_folder(url))}
    finally:
        if folder.exists() and not any(folder.iterdir()):
            try:
                folder.rmdir()
            except OSError:
                pass


# --- Derived media ----------------------------------------------------------------------------

def normalized_copy(path, multiple: int = 8, dest_dir=None) -> Path:
    """Return an image whose dimensions are multiples of ``multiple`` for tools that require it.

    The original download is never modified: when it is already aligned it is returned as-is,
    otherwise a centre-cropped ``*_normalized`` copy is written outside the media library.
    """
    from PIL import Image
    source = Path(path)
    with Image.open(source) as image:
        width, height = image.size
        if width % multiple == 0 and height % multiple == 0:
            return source
        new_w, new_h = width // multiple * multiple, height // multiple * multiple
        if not new_w or not new_h:
            raise ValueError(f'Image is smaller than {multiple}px')
        tag = hashlib.sha1(str(source.resolve()).encode('utf-8')).hexdigest()[:8]
        out_dir = Path(dest_dir) if dest_dir else data_dir() / '.derived' / 'normalized'
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f'{source.stem}_{tag}_normalized{source.suffix.lower() or ".png"}'
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            return target
        left, top = (width - new_w) // 2, (height - new_h) // 2
        cropped = image.crop((left, top, left + new_w, top + new_h))
        save_kwargs = {'quality': 95} if target.suffix in {'.jpg', '.jpeg'} else {}
        if target.suffix in {'.jpg', '.jpeg'} and cropped.mode not in {'RGB', 'L'}:
            cropped = cropped.convert('RGB')
        cropped.save(target, **save_kwargs)
    return target


def ffmpeg_filter_path(path) -> str:
    """Quote an absolute path for an ffmpeg filter option (e.g. ``subtitles=``) on any drive."""
    text = os.path.abspath(str(path)).replace('\\', '/').replace(':', '\\:')
    return "'" + text.replace("'", "'\\\\\\''") + "'"


# --- JSON persistence with backup -------------------------------------------------------------

def atomic_write_json(path, data) -> None:
    """Write JSON atomically, delegating to ``storage_utils`` when it is available."""
    try:
        from storage_utils import atomic_write_json as shared_writer
    except ImportError:
        shared_writer = None
    if shared_writer is not None:
        shared_writer(path, data)
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + '.bak')


def _load_valid(path: Path, validate: Callable[[Any], bool]):
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if not validate(data):
        raise ValueError(f'{path.name} has an unexpected structure')
    return data


def write_json_with_backup(path, data, validate: Callable[[Any], bool] = lambda d: True) -> None:
    """Keep the last good version as ``<file>.bak`` and replace the file atomically."""
    target = Path(path)
    if target.exists():
        try:
            atomic_write_json(_backup_path(target), _load_valid(target, validate))
        except (ValueError, OSError):
            pass  # never let a corrupt file overwrite the last good backup
    atomic_write_json(target, data)


def read_json_with_recovery(path, default_factory: Callable[[], Any], validate: Callable[[Any], bool] = lambda d: True):
    """Read JSON; on corruption preserve the bad file, restore ``.bak`` if valid, else start fresh."""
    target = Path(path)
    if not target.exists():
        return default_factory()
    try:
        return _load_valid(target, validate)
    except (ValueError, UnicodeDecodeError):
        pass
    preserved = target.with_name(f'{target.stem}.corrupt-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}{target.suffix}')
    os.replace(target, preserved)
    print(f'[storage] {target.name} was unreadable; preserved as {preserved.name}')
    backup = _backup_path(target)
    try:
        data = _load_valid(backup, validate)
    except (ValueError, UnicodeDecodeError, OSError):
        data = default_factory()
        atomic_write_json(target, data)  # start fresh so later loads don't treat this as a first run
        return data
    atomic_write_json(target, data)
    print(f'[storage] Restored {target.name} from backup')
    return data
