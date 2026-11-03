"""Caption identity and translation records, independent of model output and timing.

Translation record contract (docs/v5-architecture.md):
``cue.translations[lang] = {text, source, status, locked, note}`` where ``source``
is always ``sha256(normalize_ws(cue.text))``. ``make_translation`` is the only
server-side writer; ``setCueTranslation`` in ``static/captions.js`` is the only
client-side writer and uses the same normalization.
"""
import copy
import hashlib
import re
import uuid
from difflib import SequenceMatcher

STATUSES = ('approved', 'review', 'stale')
# Explicit whitespace class shared with static/captions.js (normalizeWs) so both
# sides hash byte-identical strings regardless of regex engine differences.
_WHITESPACE = re.compile('[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+')
_HEX64 = re.compile(r'[0-9a-f]{64}')
TRANSLATION_MIGRATION = 'v5_translation_source'


def normalize_ws(text):
    """Collapse whitespace runs to one space and strip the ends."""
    return _WHITESPACE.sub(' ', str(text)).strip(' ')


def source_hash(text):
    """Hash identifying the original line a translation was written for."""
    return hashlib.sha256(normalize_ws(text).encode('utf-8')).hexdigest()


def _legacy_hash(text):
    # v3.2–v4.x hashed the raw (non-normalized) line text.
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()


def matches_source(source, text):
    """True when a stored source hash belongs to this line (current or legacy hash)."""
    source = str(source or '')
    return source == source_hash(text) or source == _legacy_hash(text)


def make_translation(text, cue_text, status='approved', locked=False, note=''):
    """Build a translation record for ``cue_text``; the single server-side writer."""
    if status not in STATUSES:
        raise ValueError('Invalid translation review state.')
    if not isinstance(text, str) or len(text) > 2000:
        raise ValueError('A translation must contain at most 2,000 characters.')
    return dict(text=text.strip(), source=source_hash(cue_text), status=status,
                locked=bool(locked), note=str(note or '')[:500])


def ensure_ids(cues, project_id):
    seen = set()
    for index, cue in enumerate(cues):
        key = cue.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', key) or key in seen:
            key = uuid.uuid5(uuid.NAMESPACE_URL, f'{project_id}:{index}:{cue["start"]}:{cue["text"]}').hex
        cue['id'] = key
        seen.add(key)


def clean_translations(cue):
    records = cue.get('translations', {})
    if not isinstance(records, dict) or len(records) > 20:
        raise ValueError('Use at most 20 translation tracks.')
    result = {}
    for language, entry in records.items():
        if not re.fullmatch(r'[a-z]{2,3}', language) or not isinstance(entry, dict):
            raise ValueError('Invalid translation track.')
        text = entry.get('text', '')
        if not isinstance(text, str) or len(text) > 2000:
            raise ValueError('A translation must contain at most 2,000 characters.')
        source = str(entry.get('source', ''))
        status = entry.get('status', 'review')
        if status not in STATUSES:
            raise ValueError('Invalid translation review state.')
        if matches_source(source, cue['text']):
            # Legacy (raw-text) hashes are accepted and rewritten to the normalized form.
            source = source_hash(cue['text'])
        else:
            status = 'stale'
        result[language] = dict(text=text.strip(), source=source, status=status,
                                locked=bool(entry.get('locked', False)),
                                note=str(entry.get('note', ''))[:500])
    return result


def shows_duplicate(cue, translation, hide_duplicates):
    """Whether a translation equal to its original line should still be displayed."""
    if not hide_duplicates or cue.get('show_duplicate_translation'):
        return True
    return normalize_ws(translation) != normalize_ws(cue['text'])


def export_cues(cues, language='en', mode='original', hide_duplicates=True, skip_missing=False):
    """Export only approved translations; ``skip_missing`` drops untranslated lines in translation mode."""
    if mode not in {'original', 'translation', 'both'}:
        raise ValueError('Choose original, translation or both.')
    result = []
    for original in cues:
        cue = copy.deepcopy(original)
        entry = clean_translations(cue).get(language)
        translated = entry['text'] if entry and entry['status'] == 'approved' else ''
        if mode == 'translation':
            if not translated:
                if skip_missing:
                    continue
                raise ValueError('Approve a translation for every line before translation-only export.')
            cue.update(text=translated, words=[])
        elif mode == 'both' and translated and shows_duplicate(cue, translated, hide_duplicates):
            cue.update(text=cue['text']+'\n'+translated, words=[])
        result.append(cue)
    return result


def translation_report(cues, language, hide_duplicates=True):
    """Summarize which lines would be missing from a bilingual/translation export."""
    report = dict(language=language, total=len(cues), approved=0, review=[], stale=[], missing=[],
                  hidden_duplicates=[])
    for index, cue in enumerate(cues):
        entry = clean_translations(cue).get(language)
        item = dict(id=cue.get('id'), index=index, text=cue['text'],
                    translation=entry['text'] if entry else '', status=entry['status'] if entry else 'missing')
        if not entry or not entry['text']:
            report['missing'].append(item)
        elif entry['status'] == 'approved':
            report['approved'] += 1
            if not shows_duplicate(cue, entry['text'], hide_duplicates):
                report['hidden_duplicates'].append(item)
        else:
            report[entry['status']].append(item)
    return report


def migrate_translation_sources(cues):
    """Repair records written with a raw-text or ``'copilot'`` source (v4.x writer bug).

    Returns the number of repaired records. Translation text is never removed.
    """
    repaired = 0
    for cue in cues:
        records = cue.get('translations')
        if not isinstance(records, dict):
            continue
        for entry in records.values():
            if not isinstance(entry, dict):
                continue
            source = str(entry.get('source', ''))
            if _HEX64.fullmatch(source):
                continue
            text = entry.get('text', '')
            has_text = isinstance(text, str) and bool(text.strip())
            if source and normalize_ws(source) == normalize_ws(cue.get('text', '')):
                # The inline editor stored the line itself: the translation was approved for this text.
                entry['source'] = source_hash(cue['text'])
                if has_text:
                    entry['status'] = 'approved'
            elif source == 'copilot':
                entry['source'] = source_hash(cue.get('text', ''))
                if has_text:
                    entry['status'] = 'review'
            elif source:
                # Raw text of an older version of the line: keep it visibly stale.
                entry['source'] = source_hash(source)
                entry['status'] = 'stale'
            else:
                entry['source'] = source_hash(cue.get('text', ''))
                entry['status'] = 'stale' if entry.get('status') == 'stale' else 'review'
            repaired += 1
    return repaired


def carry_identity(old_cues, new_cues):
    """Keep ids, translations and line styles on proposed cues whose text is unchanged.

    Lines whose text changed keep their translation records too; the source hash no
    longer matches, so they surface as stale for review instead of disappearing.
    """
    carried = ('id', 'translations', 'style_override', 'show_duplicate_translation')
    old_keys = [normalize_ws(c['text']) for c in old_cues]
    new_keys = [normalize_ws(c['text']) for c in new_cues]
    used = {c.get('id') for c in new_cues if c.get('id')}
    for tag, a0, a1, b0, b1 in SequenceMatcher(None, old_keys, new_keys, autojunk=False).get_opcodes():
        if tag not in ('equal', 'replace') or (tag == 'replace' and a1 - a0 != b1 - b0):
            continue
        for old, new in zip(old_cues[a0:a1], new_cues[b0:b1]):
            for key in carried:
                if key in old and key not in new and not (key == 'id' and old[key] in used):
                    new[key] = copy.deepcopy(old[key])
                    if key == 'id':
                        used.add(old[key])
    return new_cues
