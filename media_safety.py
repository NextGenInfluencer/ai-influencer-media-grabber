"""Shared filesystem and media-output validation."""
import os

MEDIA_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.mkv', '.webm', '.avi', '.gif',
                    '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.heic',
                    '.heif', '.mp3', '.wav', '.m4a', '.ogg', '.flac'}


def contained_path(path, root):
    try:
        resolved = os.path.normcase(os.path.realpath(path))
        base = os.path.normcase(os.path.realpath(root))
        return os.path.commonpath([resolved, base]) == base
    except (ValueError, TypeError, OSError):
        return False


def safe_media_name(name):
    # Browsers may supply a full Windows path even on another OS.
    name = str(name).replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(c for c in name if c not in '<>:"/\\|?*' and ord(c) >= 32)
    name = name.strip(' .')
    stem, ext = os.path.splitext(name)
    if not stem or stem.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % n for n in range(1, 10)), *('LPT%d' % n for n in range(1, 10))}:
        stem = 'media'
    return stem[:120] + ext.lower()


def crop_filter(width, height):
    ratio = f'({width}/{height})'
    return f"crop=trunc(min(iw\\,ih*{ratio})/2)*2:trunc(min(ih\\,iw/{ratio})/2)*2"
