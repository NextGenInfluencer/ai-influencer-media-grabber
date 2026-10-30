"""Caption identity and translation records, independent of model output and timing."""
import copy
import hashlib
import re
import uuid


def source_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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
        if status not in {'approved', 'review', 'stale'}:
            raise ValueError('Invalid translation review state.')
        if source != source_hash(cue['text']):
            status = 'stale'
        result[language] = dict(text=text.strip(), source=source, status=status,
                                locked=bool(entry.get('locked', False)),
                                note=str(entry.get('note', ''))[:500])
    return result


def export_cues(cues, language='en', mode='original', hide_duplicates=True):
    if mode not in {'original', 'translation', 'both'}:
        raise ValueError('Choose original, translation or both.')
    result = []
    for original in cues:
        cue = copy.deepcopy(original)
        entry = clean_translations(cue).get(language)
        translated = entry['text'] if entry and entry['status'] == 'approved' else ''
        if mode == 'translation':
            if not translated:
                raise ValueError('Approve a translation for every line before translation-only export.')
            cue.update(text=translated, words=[])
        elif mode == 'both' and translated and (not hide_duplicates or translated != cue['text']):
            cue.update(text=cue['text']+'\n'+translated, words=[])
        result.append(cue)
    return result
