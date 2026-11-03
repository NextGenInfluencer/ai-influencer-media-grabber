"""v5 translation record contract: single writer, normalized hash, recovery and review flows."""
import tests._isolation  # Must precede application imports.
import copy
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from assets import lyric_tracks
from captions import DEFAULT_STYLE, layout_rows, validate_edit
from tests import test_captions

ROOT = Path(__file__).resolve().parents[1]


def side_editor_record(cue_text, text, status='approved', locked=True):
    """What setCueTranslation() sends: sha256 of the whitespace-normalized line."""
    normalized = re.sub('[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+', ' ', cue_text).strip(' ')
    return dict(text=text, source=hashlib.sha256(normalized.encode()).hexdigest(), status=status, locked=locked, note='')


class TranslationRecordTests(unittest.TestCase):
    def test_server_and_client_hash_identically(self):
        samples = ['Hello\nworld', '  Γεια   σου  ', 'Tab\there\u00a0nbsp', '사랑해  my love\u3000', 'Line\r\nbreak ']
        script = ('const {sourceHash}=require("./static/captions.js");'
                  f'Promise.all({json.dumps(samples)}.map(sourceHash)).then(h=>console.log(JSON.stringify(h)));')
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [lyric_tracks.source_hash(s) for s in samples])
        self.assertEqual(lyric_tracks.normalize_ws(' a \n\t b '), 'a b')

    def test_legacy_raw_hash_stays_approved_and_is_rewritten(self):
        text = 'Γεια σου\nκόσμε'
        legacy = hashlib.sha256(text.encode()).hexdigest()
        cue = dict(start=0, end=1, text=text, words=[], translations={'en': dict(text='Hello world', source=legacy, status='approved')})
        cleaned = validate_edit(dict(cues=[cue]), 2)['cues'][0]['translations']['en']
        self.assertEqual(cleaned['status'], 'approved')
        self.assertEqual(cleaned['source'], lyric_tracks.source_hash(text))
        # Whitespace-only edits to the original never hide the translation.
        cue['text'] = 'Γεια   σου κόσμε '
        cue['translations']['en'] = cleaned
        self.assertEqual(validate_edit(dict(cues=[cue]), 2)['cues'][0]['translations']['en']['status'], 'approved')
        cue['text'] = 'Different words'
        self.assertEqual(validate_edit(dict(cues=[cue]), 2)['cues'][0]['translations']['en']['status'], 'stale')

    def test_script_runs_split_mixed_lines_and_attach_neutral_tokens(self):
        from captions import script_runs
        self.assertEqual(script_runs('(Yeah) Γεια σου, 123 my love 사랑해'),
                         [('latin', ['(Yeah)']), ('el', ['Γεια', 'σου,', '123']), ('latin', ['my', 'love']), ('ko', ['사랑해'])])
        self.assertEqual(script_runs('123 Γεια'), [('el', ['123', 'Γεια'])])
        self.assertEqual(script_runs('Hello\nworld'), [('latin', ['Hello', 'world'])])

    def test_make_translation_is_the_server_writer(self):
        record = lyric_tracks.make_translation(' Hi ', 'Hello\n world', 'review', True, 'n' * 600)
        self.assertEqual(record['text'], 'Hi')
        self.assertEqual(record['source'], lyric_tracks.source_hash('Hello world'))
        self.assertEqual(len(record['note']), 500)
        with self.assertRaises(ValueError):
            lyric_tracks.make_translation('x', 'y', 'bogus')

    def test_recovery_rules_never_delete_text_and_are_idempotent(self):
        cues = [
            dict(text='Γεια σου', translations={'en': dict(text='Hello you', source='Γεια σου', status='stale', locked=True)}),
            dict(text='Καλή μέρα', translations={'en': dict(text='Good day', source='copilot', status='approved')}),
            dict(text='Νέο κείμενο', translations={'en': dict(text='Old meaning', source='Παλιό κείμενο', status='approved')}),
            dict(text='Merged line', translations={'en': dict(text='Combined', source='', status='stale')}),
        ]
        self.assertEqual(lyric_tracks.migrate_translation_sources(cues), 4)
        entries = [c['translations']['en'] for c in cues]
        self.assertEqual([e['status'] for e in entries], ['approved', 'review', 'stale', 'stale'])
        self.assertEqual([e['text'] for e in entries], ['Hello you', 'Good day', 'Old meaning', 'Combined'])
        self.assertTrue(entries[0]['locked'])
        snapshot = copy.deepcopy(cues)
        self.assertEqual(lyric_tracks.migrate_translation_sources(cues), 0)
        self.assertEqual(cues, snapshot)
        cleaned = [lyric_tracks.clean_translations(c)['en']['status'] for c in cues]
        self.assertEqual(cleaned, ['approved', 'review', 'stale', 'stale'])

    def test_carry_identity_keeps_translations_for_unchanged_and_flags_changed_lines(self):
        old = [dict(id='aaaaaaaa1', text='One', translations={'en': lyric_tracks.make_translation('Uno', 'One')}),
               dict(id='aaaaaaaa2', text='Two', translations={'en': lyric_tracks.make_translation('Dos', 'Two')})]
        new = [dict(text='One', start=0, end=1, words=[]), dict(text='Two changed', start=1, end=2, words=[])]
        lyric_tracks.carry_identity(old, new)
        self.assertEqual([c['id'] for c in new], ['aaaaaaaa1', 'aaaaaaaa2'])
        cleaned = [lyric_tracks.clean_translations(c)['en']['status'] for c in new]
        self.assertEqual(cleaned, ['approved', 'stale'])

    def test_duplicate_translation_flag_is_validated_and_overrides_hiding(self):
        cue = dict(start=0, end=1, text='Hello world', words=[],
                   translations={'en': side_editor_record('Hello world', 'Hello world')})
        style = {**DEFAULT_STYLE, 'track_mode': 'both', 'layout_enabled': True}
        self.assertEqual([r['track'] for r in layout_rows(cue, style, 1080, 1920)], ['original'])
        flagged = validate_edit(dict(cues=[{**cue, 'show_duplicate_translation': True}]), 2)['cues'][0]
        self.assertTrue(flagged['show_duplicate_translation'])
        self.assertEqual([r['track'] for r in layout_rows(flagged, style, 1080, 1920)], ['original', 'translation'])
        with self.assertRaises(ValueError):
            validate_edit(dict(cues=[{**cue, 'show_duplicate_translation': 'yes'}]), 2)
        report = lyric_tracks.translation_report([cue], 'en')
        self.assertEqual(len(report['hidden_duplicates']), 1)
        self.assertFalse(report['review'] or report['stale'] or report['missing'])

    def test_only_set_cue_translation_writes_translation_records(self):
        source = (ROOT / 'static' / 'captions.js').read_text(encoding='utf-8')
        writes = [m.start() for m in re.finditer(r'\.translations\s*(?:\?\.)?(?:\[[^\]]*\])?\s*(?:\?\?=|\|\|=|=(?!=))', source)]
        self.assertTrue(writes)

        def body(name):
            start = source.index(f'function {name}(')
            return start, source.index('\n    }\n', start)
        allowed = [body('setCueTranslation'), body('mergeCaptions')]
        for position in writes:
            self.assertTrue(any(a <= position <= b for a, b in allowed),
                            source[max(0, position - 120):position + 60])
        merge_start, merge_end = allowed[1]
        self.assertIn("status:'stale'", source[merge_start:merge_end])
        self.assertNotIn("source:'copilot'", source)
        self.assertNotIn('source:c.text', source)


class TranslationWorkflowTests(unittest.TestCase):
    setUp = test_captions.CaptionWorkflowTests.setUp
    tearDown = test_captions.CaptionWorkflowTests.tearDown
    wait = test_captions.CaptionWorkflowTests.wait
    j = test_captions.CaptionWorkflowTests.j
    karaoke_project = test_captions.CaptionWorkflowTests.karaoke_project

    def project_file(self, pid):
        return self.root / 'library' / 'Caption Projects' / pid / 'project.json'

    def test_side_editor_translation_survives_save_line_karaoke_and_renders(self):
        pid, data = self.karaoke_project()
        data['cues'][1]['translations'] = {'en': side_editor_record('Γεια σου', 'Hello you')}
        data['cues'][0]['translations'] = {'fr': side_editor_record('Hello\nworld', 'Bonjour le monde')}
        data['style'] = {**data['style'], 'track_mode': 'both', 'layout_enabled': True}
        saved = self.j(self.client.put('/api/captions/' + pid, json=data))
        self.assertEqual(saved['cues'][1]['translations']['en']['status'], 'approved')
        self.assertEqual(saved['cues'][0]['translations']['fr']['status'], 'approved')
        result = {'segments': [{'words': [dict(word='Γεια', start=.05, end=.3), dict(word=' σου', start=.4, end=.7)]}]}
        with patch('captions.asr.align_words', return_value=result):
            self.assertEqual(self.client.post(f'/api/captions/{pid}/karaoke',
                                              json={'revision': saved['revision'], 'index': 1, 'language': 'el'}).status_code, 202)
            after = self.wait(pid)
        self.assertEqual(len(after['cues'][1]['words']), 2)
        self.assertEqual(after['cues'][1]['translations'], saved['cues'][1]['translations'])
        self.assertEqual(after['cues'][0]['translations'], saved['cues'][0]['translations'])
        rows = self.j(self.client.post(f'/api/captions/{pid}/layout', json={'cue': after['cues'][1], 'style': after['style']}))['rows']
        translation = [r for r in rows if r['track'] == 'translation']
        self.assertEqual([r['text'] for r in translation], ['Hello you'])
        self.assertFalse(translation[0].get('pending'))
        with self.client.get(f'/api/captions/{pid}/srt?mode=both&language=en') as response:
            self.assertIn('Γεια σου\nHello you'.encode(), response.data.replace(b'\r', b''))

    def test_copilot_review_is_visible_in_editor_preview_only(self):
        pid, data = self.karaoke_project()
        data['cues'][1]['translations'] = {'en': side_editor_record('Γεια σου', 'Hi there', status='review', locked=False)}
        style = {**data['style'], 'track_mode': 'both', 'layout_enabled': True}
        data['style'] = style
        saved = self.j(self.client.put('/api/captions/' + pid, json=data))
        cue = saved['cues'][1]
        self.assertEqual(cue['translations']['en']['status'], 'review')
        export_rows = self.j(self.client.post(f'/api/captions/{pid}/layout', json={'cue': cue, 'style': style}))['rows']
        self.assertEqual([r['track'] for r in export_rows], ['original'])
        editor_rows = self.j(self.client.post(f'/api/captions/{pid}/layout', json={'cue': cue, 'style': style, 'editor_preview': True}))['rows']
        pending = [r for r in editor_rows if r['track'] == 'translation']
        self.assertEqual(pending[0]['text'], 'Hi there')
        self.assertTrue(pending[0]['pending'])
        report = self.j(self.client.get(f'/api/captions/{pid}/translation-status?language=en'))
        self.assertEqual([item['index'] for item in report['review']], [1])
        self.assertEqual([item['index'] for item in report['missing']], [0])
        with self.client.get(f'/api/captions/{pid}/srt?mode=both&language=en') as response:
            self.assertNotIn(b'Hi there', response.data)
        self.assertEqual(self.client.get(f'/api/captions/{pid}/srt?mode=translation&language=en').status_code, 400)
        with self.client.get(f'/api/captions/{pid}/srt?mode=translation&language=en&skip_missing=1') as response:
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b'-->', response.data)

    def test_recovery_migration_backs_up_once_and_restores_hidden_translations(self):
        pid, data = self.karaoke_project()
        location = self.project_file(pid)
        raw = json.loads(location.read_text(encoding='utf-8'))
        raw['cues'][1]['translations'] = {'en': dict(text='Hello you', source='Γεια σου', status='stale', locked=True, note='')}
        raw['cues'][0]['translations'] = {'en': dict(text='Hi world', source='copilot', status='approved', locked=False, note='')}
        location.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
        original_bytes = location.read_bytes()
        recovered = self.j(self.client.get('/api/captions/' + pid))
        self.assertEqual(recovered['cues'][1]['translations']['en']['status'], 'approved')
        self.assertEqual(recovered['cues'][1]['translations']['en']['text'], 'Hello you')
        self.assertEqual(recovered['cues'][0]['translations']['en']['status'], 'review')
        self.assertIn(lyric_tracks.TRANSLATION_MIGRATION, recovered['migrations'])
        backup = location.parent / 'pre-v5-project.json'
        self.assertEqual(backup.read_bytes(), original_bytes)
        migrated = location.read_bytes()
        again = self.j(self.client.get('/api/captions/' + pid))
        self.assertEqual(location.read_bytes(), migrated)
        self.assertEqual(again['cues'], recovered['cues'])
        self.assertEqual(backup.read_bytes(), original_bytes)
        rows = self.j(self.client.post(f'/api/captions/{pid}/layout', json={
            'cue': again['cues'][1], 'style': {**again['style'], 'track_mode': 'both', 'layout_enabled': True}}))['rows']
        self.assertIn('Hello you', [r['text'] for r in rows])

    def test_mixed_line_retry_aligns_each_script_run_in_its_language(self):
        pid, data = self.karaoke_project()
        data['cues'][1]['text'] = 'Γεια σου my love'
        data['cues'][1]['translations'] = {'en': side_editor_record('Γεια σου my love', 'Hello you my love')}
        saved = self.j(self.client.put('/api/captions/' + pid, json=data))
        calls = []

        def align(audio, text, language):
            calls.append((text, language, round(len(audio) / 16000, 2)))
            if text == 'Γεια σου my love':  # whole-line coarse pass
                return {'segments': [{'words': [dict(word='Γεια', start=.05, end=.2), dict(word=' σου', start=.2, end=.4),
                                                dict(word=' my', start=.4, end=.6), dict(word=' love', start=.6, end=.85)]}]}
            self.assertEqual((text, language), ('my love', 'en'))
            return {'segments': [{'words': [dict(word='my', start=.05, end=.2), dict(word=' love', start=.25, end=.5)]}]}
        with patch('captions.asr.align_words', side_effect=align):
            self.client.post(f'/api/captions/{pid}/karaoke', json={'revision': saved['revision'], 'index': 1, 'language': 'auto'})
            after = self.wait(pid)
        self.assertEqual([c[:2] for c in calls], [('Γεια σου my love', 'el'), ('my love', 'en')])
        self.assertLess(calls[1][2], calls[0][2], 'Latin run is aligned over its own sub-range')
        cue = after['cues'][1]
        self.assertEqual([w['text'] for w in cue['words']], ['Γεια', 'σου', 'my', 'love'])
        starts = [w['start'] for w in cue['words']]
        self.assertEqual(starts, sorted(starts))
        self.assertGreaterEqual(cue['words'][2]['start'], cue['words'][1]['end'])
        self.assertIn('Aligned per language (el + en)', cue['karaoke']['note'])
        self.assertEqual(cue['karaoke']['state'], 'review')
        self.assertEqual(cue['translations'], saved['cues'][1]['translations'])

    def test_correct_lyrics_keeps_translations_of_unchanged_lines(self):
        pid, data = self.karaoke_project()
        data['cues'][1]['translations'] = {'en': side_editor_record('Γεια σου', 'Hello you')}
        saved = self.j(self.client.put('/api/captions/' + pid, json=data))
        lyrics = '\n'.join(c['text'].replace('\n', ' ') for c in saved['cues'])
        options = dict(revision=saved['revision'], text=lyrics, start=0, end=saved['duration'], review=True)
        self.assertEqual(self.client.post(f'/api/captions/{pid}/correct-lyrics', json=options).status_code, 202)
        proposed = self.wait(pid)
        applied = self.j(self.client.post(f'/api/captions/{pid}/lyric-proposal', json=dict(
            revision=proposed['revision'], id=proposed['lyric_proposal']['id'], action='apply')))
        greek = next(c for c in applied['cues'] if c['text'] == 'Γεια σου')
        self.assertEqual(greek['id'], saved['cues'][1]['id'])
        self.assertEqual(greek['translations'], saved['cues'][1]['translations'])


if __name__ == '__main__':
    unittest.main()
