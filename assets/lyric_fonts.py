"""Resolve missing glyphs to the same bundled fonts for layout and rendering."""
from functools import lru_cache
from pathlib import Path
import unicodedata
from PIL import ImageFont


@lru_cache(maxsize=32)
def _font(path, modified):
    return ImageFont.truetype(path, 32)


@lru_cache(maxsize=8192)
def _has_glyph(path, modified, character):
    font = _font(path, modified)
    mask = font.getmask(character)
    missing = font.getmask(chr(0x10ffff))
    return (mask.size, bytes(mask)) != (missing.size, bytes(missing))


def _is_greek(character):
    code = ord(character)
    return 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF


def _supports_character(path, modified, character):
    if not _has_glyph(path, modified, character):
        return False
    if _is_greek(character):
        # Latin/CJK fonts often include math symbols (μ, π, Δ, Ω) or unaccented Greek
        # without full modern Greek tonos support; keep Greek words in a full Greek font.
        return (_has_glyph(path, modified, 'α')
                and _has_glyph(path, modified, 'ά')
                and _has_glyph(path, modified, 'ώ'))
    return True


def runs(text, family, locate):
    """Group adjacent glyphs; keep spelling and whitespace unchanged.

    Pillow exposes rendered glyph masks, not a font's cmap. Compare against its
    missing-glyph mask, with a bounded cache invalidated by file modification.
    Unsupported symbols retain the requested font and platform fallback.
    """
    candidates = []
    fallback_fonts = ('Black Han Sans', 'Roboto', 'Noto Sans KR') if family == 'Impact' else ('Roboto', 'Noto Sans KR')
    for name in dict.fromkeys((family, *fallback_fonts)):
        path = Path(locate(name))
        if path.is_file():
            candidates.append((name, str(path), path.stat().st_mtime_ns))
    result = []
    last_non_space = family
    for character in text:
        chosen = family
        if not character.isspace() and unicodedata.category(character) not in ('Cf','Cc'):
            for name, path, modified in candidates:
                try:
                    if _supports_character(path, modified, character):
                        chosen = name
                        last_non_space = name
                        break
                except OSError:
                    continue
        elif character.isspace() and last_non_space != family:
            chosen = last_non_space
        if result and result[-1]['font'] == chosen:
            result[-1]['text'] += character
        else:
            result.append(dict(font=chosen,text=character))
    return result
