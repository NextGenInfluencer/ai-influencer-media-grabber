"""Normalize photo/carousel fallback results into the video download pipeline."""
import os
import sys
import uuid
from pathlib import Path
import requests
import yt_dlp
import yt_dlp.extractor.instagram
import job_process as subprocess
from media_safety import MEDIA_EXTENSIONS, safe_media_name

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Referer': 'https://www.instagram.com/'
}


class InstagramMediaIE(yt_dlp.extractor.instagram.InstagramIE):
    """Instagram extractor that permits extraction of image-only posts and carousels."""
    def raise_no_formats(self, msg, expected=False):
        pass


def extract_instagram_preview(url, browser=None):
    """Extract metadata for UI preview without requiring video formats."""
    ydl_opts = {'quiet': True, 'no_warnings': True}
    if browser and browser != 'none':
        if browser == 'cookies.txt':
            ydl_opts['cookiefile'] = 'cookies.txt'
        else:
            ydl_opts['cookiesfrombrowser'] = (browser, None, None, None)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ie = InstagramMediaIE(ydl)
        info = ie._real_extract(url)

    if not info:
        return None

    entries = info.get('entries') if info.get('_type') == 'playlist' else [info]
    first_entry = entries[0] if entries else info
    uploader = info.get('uploader') or info.get('channel') or first_entry.get('uploader') or 'Instagram Creator'
    title = info.get('title') or first_entry.get('title') or f"Post by {uploader}"
    
    thumb_url = ''
    thumbs = first_entry.get('thumbnails') or info.get('thumbnails') or []
    if thumbs:
        thumb_url = thumbs[-1].get('url', '')

    return {
        'title': title,
        'uploader': uploader,
        'thumbnail': thumb_url,
        'duration': first_entry.get('duration') or 0
    }


def instagram_download(url, output_path, browser, report, custom_name=None):
    """Download Instagram carousel slides or photo/video posts directly."""
    report({'status': 'Fetching Instagram post details...'})
    ydl_opts = {'quiet': True, 'no_warnings': True}
    if browser and browser != 'none':
        if browser == 'cookies.txt':
            ydl_opts['cookiefile'] = 'cookies.txt'
        else:
            ydl_opts['cookiesfrombrowser'] = (browser, None, None, None)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ie = InstagramMediaIE(ydl)
        info = ie._real_extract(url)

    if not info:
        raise RuntimeError('Could not extract Instagram post data')

    entries = info.get('entries') if info.get('_type') == 'playlist' else [info]
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
        raw_title = custom_name if custom_name else (entry.get('title') or info.get('title') or f"Post by {safe_uploader}")
        clean_title = safe_media_name(raw_title).rsplit('.', 1)[0]
        prefix = f"[{idx}/{total}] " if total > 1 else ""

        # Check for video formats
        formats = [f for f in entry.get('formats', []) if f.get('url') and f.get('vcodec') != 'none']
        if formats:
            best_fmt = max(formats, key=lambda f: (f.get('width') or 0) * (f.get('height') or 0))
            media_url = best_fmt['url']
            ext = 'mp4'
        else:
            thumbs = entry.get('thumbnails') or []
            if not thumbs:
                continue
            media_url = thumbs[-1]['url']
            ext = 'jpg'
            if raw_title.startswith('Video by '):
                raw_title = 'Photo by ' + raw_title[9:]
                clean_title = safe_media_name(raw_title).rsplit('.', 1)[0]

        if total > 1:
            filename = f"{idx:02d} - {clean_title}_{entry_id}.{ext}"
        else:
            filename = f"{clean_title}_{entry_id}.{ext}"

        dest_file = target_dir / filename
        c = 1
        stem = dest_file.stem
        while dest_file.exists():
            dest_file = target_dir / f"{stem} ({c}).{ext}"
            c += 1

        report({'status': f"{prefix}Downloading slide {idx}/{total} ({ext.upper()})..."})

        resp = requests.get(media_url, headers=_HEADERS, stream=True, timeout=45)
        resp.raise_for_status()

        with open(dest_file, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                subprocess.check_cancelled()
                if chunk:
                    f.write(chunk)

        if ext == 'jpg':
            try:
                from PIL import Image
                with Image.open(dest_file) as im:
                    w, h = im.size
                    if w % 8 != 0 or h % 8 != 0:
                        new_w = (w // 8) * 8
                        new_h = (h // 8) * 8
                        cropped = im.crop((0, 0, new_w, new_h))
                        cropped.save(dest_file, 'JPEG', quality=95)
            except Exception:
                pass

        downloaded_entries.append({
            'filepath': str(dest_file),
            '_filename': str(dest_file),
            'title': raw_title,
            'uploader': raw_uploader,
            'webpage_url': url,
            'extractor_key': 'Instagram'
        })

    if not downloaded_entries:
        raise RuntimeError('No media files could be downloaded from this Instagram post')

    return {'_type': 'playlist', 'entries': downloaded_entries}


def gallery_download(url, output_path, browser, report, custom_name=None):
    if 'instagram.com' in url.lower():
        try:
            return instagram_download(url, output_path, browser, report, custom_name=custom_name)
        except Exception as e:
            err = str(e).lower()
            if 'cancelled' in err:
                raise
            report({'status': f'Native Instagram download failed ({e}); trying gallery-dl fallback...'})

    folder = Path(output_path) / ('Gallery-' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    try:
        command = [sys.executable, '-m', 'gallery_dl', '-d', str(folder)]
        if browser and browser != 'none':
            command.extend(['--cookies' if browser == 'cookies.txt' else '--cookies-from-browser', browser])
        command.append(url)
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace') as process:
            for line in process.stdout:
                report({'status': 'gallery-dl: ' + line.strip()[-200:]})
            if process.wait() != 0:
                raise RuntimeError('Gallery download failed; see activity log')
        subprocess.check_cancelled()
        entries = [{'filepath': str(file), '_filename': str(file), 'title': file.stem,
                    'webpage_url': url, 'extractor_key': 'Other'}
                   for file in folder.rglob('*') if file.is_file() and file.suffix.lower() in MEDIA_EXTENSIONS]
        if not entries:
            raise RuntimeError('No media files were downloaded')
        return {'_type': 'playlist', 'entries': entries}
    finally:
        # Clean up empty folder if download failed or produced no files in folder root
        if folder.exists() and not any(folder.iterdir()):
            try:
                folder.rmdir()
            except Exception:
                pass
