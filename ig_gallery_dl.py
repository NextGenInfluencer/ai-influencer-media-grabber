"""Resilient gallery-dl runner wrapper for Instagram profile Reels & extensionless video CDN URLs."""
from __future__ import annotations

import sys

_LOGIN_ERROR_MARKERS = (
    'redirect to login',
    'accounts/login',
    'login_required',
    'login required',
    'checkpoint_required',
    'not logged in',
    '401 unauthorized',
)

_PATCHED = False


def _is_login_exception(exc: BaseException) -> bool:
    text = str(exc or '').lower()
    return any(marker in text for marker in _LOGIN_ERROR_MARKERS)


def patch_gallery_dl_instagram() -> None:
    """Patch gallery-dl's Instagram extractors idempotently for GraphQL Reels and .mp4 extensions."""
    global _PATCHED
    if _PATCHED:
        return

    from gallery_dl.extractor.common import Message
    from gallery_dl.extractor.instagram import InstagramExtractor, InstagramReelsExtractor

    orig_items = InstagramExtractor.items

    def _patched_items(self):
        for msg, url, kwdict in orig_items(self):
            if (
                msg == Message.Url
                and isinstance(kwdict, dict)
                and (kwdict.get('video_url') or str(url).startswith('ytdl:'))
                and not kwdict.get('extension')
            ):
                kwdict['extension'] = 'mp4'
            yield msg, url, kwdict

    def _patched_reels_posts(self):
        for entry in self.api.user_reels(self.item):
            media = entry.get('media') if isinstance(entry, dict) else None
            if not isinstance(media, dict):
                continue
            if media.get('video_versions') or media.get('video_dash_manifest'):
                normalized = dict(media)
                normalized.setdefault('caption', None)
                if not normalized.get('user'):
                    normalized['user'] = self._user or {}
                normalized.setdefault('product_type', 'clips')
                yield normalized
                continue
            code = media.get('code')
            if not code:
                continue
            try:
                yield from self.api.media(code)
            except Exception as exc:
                if _is_login_exception(exc):
                    raise
                self.log.warning('Skipping media info lookup for reel %s: %s', code, exc)

    InstagramExtractor.items = _patched_items
    InstagramReelsExtractor.posts = _patched_reels_posts
    _PATCHED = True


def main() -> int:
    import gallery_dl

    patch_gallery_dl_instagram()
    return int(gallery_dl.main() or 0)


if __name__ == '__main__':
    sys.exit(main())
