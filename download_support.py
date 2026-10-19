"""Normalize photo/carousel fallback results into the video download pipeline."""
import os
import sys
import uuid
from pathlib import Path
import job_process as subprocess
from media_safety import MEDIA_EXTENSIONS

def gallery_download(url, output_path, browser, report):
    folder = Path(output_path) / ('Gallery-' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
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
