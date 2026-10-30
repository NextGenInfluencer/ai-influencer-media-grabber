"""Caption validation and complete media workflow with real FFmpeg rendering."""
import tests._isolation  # Must precede application imports.
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import threading
from typing import Any
import unittest
from unittest.mock import patch

from flask import Flask
import imageio_ffmpeg
from captions import (DEFAULT_STYLE, BUNDLED_FONTS, FONT_DIR, font_scale, visualizer_bars,
                      ass_text, parse_subtitles, register_captions,
                      srt_text, validate_edit, lyric_lines, aligned_cues,
                      match_lyrics_to_transcription, normalize_lyric_text)
import job_process


class CaptionDataTests(unittest.TestCase):
    def test_lyrics_preserve_repetition_and_unicode_and_skip_section_headers(self):
        self.assertEqual(lyric_lines('[Verse 1]\nΓεια σου\n\n[Chorus]\nΓεια σου'), ['Γεια σου','Γεια σου'])
        for text in ['', '[Verse]', 'x'*1001, 42]:
            with self.assertRaises(ValueError): lyric_lines(text)

    def test_alignment_keeps_text_line_breaks_and_offsets(self):
        result={'segments':[{'words':[{'word':' Γεια','start':.1,'end':.3},{'word':' σου','start':.3,'end':.6},
                                    {'word':' Γεια','start':1,'end':1.2},{'word':' σου','start':1.2,'end':1.5}]}]}
        cues=aligned_cues(result,['Γεια σου','Γεια σου'],3,6,2)
        self.assertEqual([c['text'] for c in cues],['Γεια σου','Γεια σου'])
        self.assertEqual(cues[0]['start'],3.1)
        self.assertEqual(cues[1]['end'],4.5)
        with self.assertRaises(ValueError): aligned_cues(result,['Different text'],0,6,2)
        result['segments'][0]['words'][0]['end']=.1
        with self.assertRaises(ValueError): aligned_cues(result,['Γεια σου','Γεια σου'],0,6,2)

    def test_pasted_lyrics_recover_uncertain_words_and_flag_only_affected_lines(self):
        result={'segments':[{'words':[
            dict(word='Καλή',start=.1,end=.4),dict(word='μέρα',start=.4,end=.8),
            dict(word='για',start=1,end=1),dict(word='σένα',start=1.5,end=1.9),
            dict(word='ξανά',start=2,end=2.3)]}]}
        cues=aligned_cues(result,['Καλή μέρα','για σένα','ξανά'],0,3,3,recover=True)
        self.assertEqual([c['text'] for c in cues],['Καλή μέρα','για σένα','ξανά'])
        self.assertNotIn('karaoke',cues[0]);self.assertNotIn('karaoke',cues[2])
        self.assertEqual(cues[1]['karaoke']['state'],'review')
        self.assertIn('estimated',cues[1]['karaoke']['note'])
        self.assertEqual(cues[1]['words'][0]['start'],.8)
        self.assertEqual(cues[1]['words'][0]['end'],1.5)
        self.assertEqual(cues[2]['start'],2)
        result['segments'][0]['words'][-1].update(start=3,end=3)
        cues=aligned_cues(result,['Καλή μέρα','για σένα','ξανά'],0,3,3,recover=True)
        self.assertEqual(cues[-1]['end'],3)
        self.assertEqual(cues[-1]['karaoke']['state'],'review')
        for word in result['segments'][0]['words']: word.update(start=0,end=0)
        with self.assertRaisesRegex(ValueError,'reliable'):
            aligned_cues(result,['Καλή μέρα','για σένα','ξανά'],0,3,3,recover=True)

    def test_aligned_cues_pathological_zero_duration_and_boundary_overlap(self):
        # Simulates real Whisper output with zero-duration words and boundary edge cases
        result = {'segments': [{'words': [
            dict(word='Πάλι', start=0.1, end=0.8),
            dict(word='μόνος', start=0.8, end=1.5),
            dict(word='με', start=1.5, end=1.5), # zero duration!
            dict(word='το', start=1.5, end=1.5), # zero duration!
            dict(word='ίδιο', start=1.8, end=2.4),
            dict(word='δωμάτιο', start=2.4, end=3.0),
            dict(word='ξανά', start=3.0, end=3.0), # tail zero-duration word at limit!
        ]}]}
        lines = ['Πάλι μόνος', 'με το ίδιο δωμάτιο', 'ξανά']
        # Without recover, should raise uncertain timing
        with self.assertRaises(ValueError):
            aligned_cues(result, lines, 0, 3.0, 3.0, recover=False)
        # With recover=True, must recover without error and flag affected lines
        cues = aligned_cues(result, lines, 0, 3.0, 3.0, recover=True)
        self.assertEqual(len(cues), 3)
        self.assertEqual([c['text'] for c in cues], lines)
        self.assertEqual(cues[1]['karaoke']['state'], 'review')
        self.assertTrue(all(w['end'] > w['start'] for c in cues for w in c['words']))

    def test_aligned_cues_flags_stretched_word_timing_across_interlude(self):
        result = {'segments': [{'words': [
            dict(word='Έγινες', start=62.84, end=63.38),
            dict(word='το', start=63.38, end=63.50),
            dict(word='γιατρικό', start=63.50, end=64.26),
            dict(word='μου', start=64.26, end=81.82),
            dict(word='Πάμε', start=82.74, end=83.30),
        ]}]}
        cues = aligned_cues(result, ['Έγινες το γιατρικό μου', 'Πάμε'], 0, 90.0, 90.0, recover=True)
        self.assertEqual(cues[0]['karaoke']['state'], 'review')
        self.assertIn('stretched', cues[0]['karaoke']['note'])
        self.assertNotIn('karaoke', cues[1])

    def test_match_lyrics_to_transcription_phonetic_and_preservation(self):
        transcribed = [
            dict(start=1.0, end=4.0, text='Παλή μόνος μέσα το ίδιο δω μάτι', words=[]),
            dict(start=4.5, end=8.0, text='Ξέρου φτεο εγώ που σε αγάπησα', words=[]),
            dict(start=8.5, end=12.0, text='Το Ξυγλόβ με τραβά στο κενό', words=[]),
        ]
        correct = [
            'Πάλι μόνος μες στο ίδιο δωμάτιο',
            'Ξέρω φταίω εγώ που σε αγάπησα',
            'Το toxic love με τραβά στο κενό',
        ]
        matched = match_lyrics_to_transcription(transcribed, correct, 15.0)
        self.assertEqual(len(matched), 3)
        self.assertEqual([c['text'] for c in matched], correct)
        self.assertEqual(matched[0]['start'], 1.0)
        self.assertEqual(matched[0]['end'], 4.0)
        self.assertEqual(matched[1]['start'], 4.5)
        self.assertEqual(matched[1]['end'], 8.0)
        self.assertEqual(matched[2]['start'], 8.5)
        self.assertEqual(matched[2]['end'], 12.0)
        # Words must be generated and valid
        for c in matched:
            self.assertTrue(all(w['end'] > w['start'] for w in c['words']))

    def test_match_lyrics_to_transcription_unmatched_lines(self):
        transcribed = [
            dict(start=1.0, end=4.0, text='Πρώτη γραμμή τραγουδιού', words=[]),
            dict(start=10.0, end=14.0, text='Τρίτη γραμμή τραγουδιού', words=[]),
        ]
        correct = [
            'Πρώτη γραμμή τραγουδιού',
            'Δεύτερη γραμμή που δεν είχε καταγραφεί', # un-transcribed bridge
            'Τρίτη γραμμή τραγουδιού',
        ]
        matched = match_lyrics_to_transcription(transcribed, correct, 20.0)
        self.assertEqual(len(matched), 3)
        self.assertEqual([c['text'] for c in matched], correct)
        # Line 1 must be flagged as review
        self.assertEqual(matched[1]['karaoke']['state'], 'review')
        self.assertIn('Unmatched', matched[1]['karaoke']['note'])
        # Timing must be within gap (between 4.0 and 10.0)
        self.assertGreaterEqual(matched[1]['start'], 4.0)
        self.assertLessEqual(matched[1]['end'], 10.0)

    def test_unicode_roundtrip_and_lrc_repeated_lines(self):
        text = '1\n00:00:00,100 --> 00:00:01,500\nΓεια σου\nHello\n'
        cues = parse_subtitles(text, 4)
        self.assertEqual(parse_subtitles(srt_text(cues), 4), cues)
        lrc = parse_subtitles('[00:00.50][00:02.00]Hello\n[00:03.00]\n', 4)
        self.assertEqual([(c['start'], c['end']) for c in lrc], [(.5, 2), (2, 3)])

    def test_invalid_times_and_overlaps(self):
        for start, end in [(float('nan'), 1), (-1, 1), (2, 1), (0, 5)]:
            with self.assertRaises(ValueError):
                validate_edit({'cues':[dict(start=start,end=end,text='test')]},4)
        with self.assertRaises(ValueError):
            parse_subtitles('1\n00:00:00,000 --> 00:00:02,000\none\n\n2\n00:00:01,000 --> 00:00:03,000\ntwo',4)

    def test_word_text_must_match_and_markup_cannot_execute(self):
        cue=dict(start=0,end=1,text=r'{\pos(0,0)} Hi',words=[])
        data=validate_edit({'cues':[cue]},2)
        output=ass_text({**data,'width':320,'height':240})
        self.assertNotIn(r'{\pos(0,0)}',output)
        cue['words']=[dict(start=0,end=1,text='different')]
        with self.assertRaises(ValueError):
            validate_edit({'cues':[cue]},2)

    def test_karaoke_does_not_highlight_during_word_gaps(self):
        cue=dict(start=0,end=2,text='Hello world',words=[
            dict(start=.2,end=.6,text='Hello'),dict(start=1,end=1.5,text='world')])
        data=validate_edit({'cues':[cue],'style':{**DEFAULT_STYLE,'karaoke':True}},2)
        lines=ass_text({**data,'width':320,'height':240}).splitlines()
        gap=next(line for line in lines if line.startswith('Dialogue: 0,00:00:00.60,00:00:01.00'))
        self.assertNotIn(r'{\c',gap)

    def test_karaoke_export_preserves_explicit_line_breaks(self):
        cue=dict(start=0,end=2,text='Hello\nworld',words=[dict(start=0,end=1,text='Hello'),dict(start=1,end=2,text='world')])
        data=validate_edit({'cues':[cue],'style':{**DEFAULT_STYLE,'karaoke':True}},2)
        events=[line for line in ass_text({**data,'width':320,'height':240}).splitlines() if line.startswith('Dialogue:')]
        self.assertTrue(events)
        self.assertTrue(all(r'\N' in line for line in events))

    def test_bundled_multilingual_fonts_and_ofl_licenses(self):
        for family in ('Montserrat', 'Roboto', 'Noto Sans KR', 'Oswald', 'Lobster', 'Bangers'):
            self.assertIn(family, BUNDLED_FONTS)
            ttf_path = FONT_DIR / BUNDLED_FONTS[family]
            self.assertTrue(ttf_path.is_file(), f'Missing font file: {ttf_path}')
            self.assertGreater(font_scale(family), 0.9)
            validated = validate_edit({'cues': [], 'style': {**DEFAULT_STYLE, 'font': family}}, 5)
            self.assertEqual(validated['style']['font'], family)
        for license_name in ('montserrat-OFL.txt', 'roboto-OFL.txt', 'notosanskr-OFL.txt',
                             'oswald-OFL.txt', 'lobster-OFL.txt', 'bangers-OFL.txt'):
            self.assertTrue((FONT_DIR / license_name).is_file(), f'Missing OFL file: {license_name}')

    def test_cumulative_karaoke_word_pop_boxed_captions_and_visualizer_ass(self):
        cue = dict(start=0, end=2, text='Φταίω Εγώ', words=[
            dict(start=0.2, end=0.8, text='Φταίω'),
            dict(start=1.0, end=1.8, text='Εγώ')
        ])
        style = {
            **DEFAULT_STYLE,
            'font': 'Roboto',
            'karaoke': True,
            'cumulative': True,
            'word_pop': True,
            'background': True,
            'visualizer': True,
            'visualizer_style': 'spectrum',
            'visualizer_position': 'bottom',
            'visualizer_height': 20,
            'visualizer_sensitivity': 1.2,
            'visualizer_color': '#00f5d4'
        }
        data = validate_edit({'cues': [cue], 'style': style}, 2)
        ass = ass_text({**data, 'width': 640, 'height': 360, 'duration': 2.0, 'peaks': [0.2, 0.6, 0.9, 0.4]})
        self.assertIn('Style: Default,Roboto,', ass)
        self.assertIn('&H38140C0A', ass)
        # Check visualizer vector events on Layer -1
        vis_events = [line for line in ass.splitlines() if line.startswith('Dialogue: -1,')]
        self.assertTrue(vis_events)
        self.assertIn(r'\p1', vis_events[0])
        # During word 2 (1.00 to 1.80), word 1 remains lit (cumulative) and word 2 has both color and 115% scale pop
        word2_line = next(line for line in ass.splitlines() if line.startswith('Dialogue: 0,00:00:01.00,00:00:01.80'))
        self.assertIn(r'Φταίω{\r}', word2_line)
        self.assertIn(r'\fscx115\fscy115}Εγώ{\r}', word2_line)
        # Verify visualizer_bars math for top, center, and bottom
        for mode in ('spectrum', 'waveform'):
            for pos in ('bottom', 'center', 'top'):
                rects = visualizer_bars([0.1, 0.5, 0.9], 2.0, 1.0, 640, 360, {**style, 'visualizer_style': mode, 'visualizer_position': pos})
                self.assertEqual(len(rects), 36 if mode == 'spectrum' else 48)
                self.assertTrue(all(x2 > x1 and y2 > y1 for x1, y1, x2, y2 in rects))
        # Verify identical visual math between Python visualizer_bars() and JS CaptionTiming.visualizerBars()
        py_rects = [list(r) for r in visualizer_bars([0.15, 0.45, 0.85, 0.35], 4.0, 1.75, 1080, 1920, style)]
        js_check = subprocess.run(
            ['node', '-e', f'const {{visualizerBars}}=require("./static/captions.js"); console.log(JSON.stringify(visualizerBars([0.15,0.45,0.85,0.35],4.0,1.75,1080,1920,{json.dumps(style)})));'],
            capture_output=True, text=True, check=True
        )
        self.assertEqual(py_rects, json.loads(js_check.stdout.strip()))


class CaptionWorkflowTests(unittest.TestCase):
    def j(self, response) -> dict[str, Any]:
        data = response.json
        self.assertIsNotNone(data)
        assert isinstance(data, dict)
        return data

    def karaoke_project(self):
        response = self.client.post('/api/captions', data={'video': (io.BytesIO(self.source.read_bytes()), 'sample.mp4')})
        pid = self.j(response)['id']
        data = self.wait(pid)
        data['cues'] = [dict(start=.1, end=.9, text='Hello\nworld', words=[]), dict(start=1, end=1.9, text='Γεια σου', words=[])]
        data = self.j(self.client.put('/api/captions/' + pid, json=data))
        return pid, data

    def test_karaoke_preserves_lines_style_and_backup_and_flags_failures(self):
        pid,before=self.karaoke_project()
        languages=[]
        def align(model,audio,text,language):
            languages.append(language)
            if language=='el':raise ValueError('Uncertain words')
            return {'segments':[{'words':[dict(word='Hello',start=.05,end=.3),dict(word=' world',start=.4,end=.7)]}]}
        options=dict(revision=before['revision'],language='auto')
        with patch('captions.align_caption_words',side_effect=align):
            self.assertEqual(self.client.post(f'/api/captions/{pid}/karaoke',json=options).status_code,202)
            after=self.wait(pid)
        self.assertEqual(languages,['en','el'])
        self.assertEqual(after['style'],before['style'])
        self.assertEqual([(c['text'],c['start'],c['end']) for c in after['cues']],[(c['text'],c['start'],c['end']) for c in before['cues']])
        self.assertEqual(after['cues'][0]['karaoke']['state'],'aligned')
        self.assertEqual(after['cues'][1]['karaoke']['state'],'review')
        self.assertEqual(after['cues'][1]['words'],[])
        self.assertEqual(self.client.post(f'/api/captions/{pid}/karaoke',json=options).status_code,409)
        saved = self.j(self.client.put('/api/captions/' + pid, json=after))
        self.assertEqual(saved['cues'],after['cues'])
        restored = self.j(self.client.post(f'/api/captions/{pid}/restore-karaoke', json={'revision': saved['revision']}))
        self.assertEqual(restored['cues'],before['cues'])

    def test_karaoke_single_retry_override_and_cancel_are_transactional(self):
        pid,before=self.karaoke_project()
        result={'segments':[{'words':[dict(word='Γεια',start=.05,end=.3),dict(word=' σου',start=.4,end=.7)]}]}
        with patch('captions.align_caption_words',return_value=result) as align:
            self.client.post(f'/api/captions/{pid}/karaoke',json={'revision':before['revision'],'index':1,'language':'el'})
            after=self.wait(pid)
            self.assertEqual(align.call_count,1)
        self.assertEqual(after['cues'][0],before['cues'][0])
        self.assertEqual(len(after['cues'][1]['words']),2)
        entered,release=threading.Event(),threading.Event()
        def blocked(*args):
            entered.set();release.wait(5);return result
        with patch('captions.align_caption_words',side_effect=blocked):
            self.client.post(f'/api/captions/{pid}/karaoke',json={'revision':after['revision'],'index':1,'language':'el'})
            try:
                self.assertTrue(entered.wait(5))
                busy = self.j(self.client.get('/api/captions/' + pid))
                self.assertEqual(busy['cues'],after['cues'])
                self.assertEqual(self.client.put('/api/captions/'+pid,json=after).status_code,409)
                job_process.cancel_all()
            finally:release.set()
            cancelled=self.wait(pid,'error')
        self.assertEqual(cancelled['cues'],after['cues'])
        self.assertEqual(cancelled['karaoke_backup'],after['karaoke_backup'])
        self.assertFalse((self.root/'library'/'Caption Projects'/pid/'karaoke.wav').exists())

    def test_karaoke_mixed_language_line_is_flagged_and_keeps_linebreak(self):
        pid,data=self.karaoke_project()
        data['cues'][0]['text']='Γεια\nhello'
        data = self.j(self.client.put('/api/captions/' + pid, json=data))
        result={'segments':[{'words':[dict(word='Γεια',start=.05,end=.3),dict(word=' hello',start=.4,end=.7)]}]}
        with patch('captions.align_caption_words',return_value=result) as align:
            self.client.post(f'/api/captions/{pid}/karaoke',json={'revision':data['revision'],'index':0,'language':'auto'})
            after=self.wait(pid)
            self.assertEqual(align.call_args.args[-1],'el')
        self.assertEqual(after['cues'][0]['text'],'Γεια\nhello')
        self.assertEqual(after['cues'][0]['karaoke']['state'],'review')
        self.assertIn('Mixed',after['cues'][0]['karaoke']['note'])
        self.assertEqual(after['cues'][1],data['cues'][1])
        after['style']['karaoke']=True
        self.client.put('/api/captions/'+pid,json=after)
        self.client.post(f'/api/captions/{pid}/render',json={'preview':False})
        self.assertTrue(self.wait(pid)['last_render'])

    def test_song_composition_backgrounds_visualizer_and_font_export(self):
        from PIL import Image
        audio=self.root/'song.wav'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-i',str(self.source),'-vn',str(audio)],capture_output=True,check=True)
        image=io.BytesIO();Image.new('RGB',(120,80),'green').save(image,format='PNG')
        for background in [None, (image.getvalue(),'photo.png'), (self.source.read_bytes(),'clip.mp4')]:
            payload={'audio':(io.BytesIO(audio.read_bytes()),'song.wav'),'shape':'square','visualizer':'true','color':'#123456'}
            if background: payload['background']=(io.BytesIO(background[0]),background[1])
            response=self.client.post('/api/captions',data=payload)
            self.assertEqual(response.status_code,202,response.data)
            pid = self.j(response)['id']
            data = self.wait(pid)
            self.assertEqual((data['width'],data['height']),(1080,1080))
            self.assertAlmostEqual(data['duration'],2,delta=.1)
            self.assertTrue(data['composition']['visualizer'])
            folder=self.root/'library'/'Caption Projects'/pid
            self.assertEqual((folder/'song.wav').read_bytes(),audio.read_bytes())
        self.assertEqual(self.client.post(f'/api/captions/{pid}/render',json={'preview':True}).status_code,202)
        data=self.wait(pid)
        self.assertTrue(data['last_render'])
        data['cues']=[dict(start=0,end=1,text='Hello music',words=[])]
        data['style']['font']='Oswald'
        self.assertEqual(self.client.put('/api/captions/'+pid,json=data).status_code,200)
        self.assertEqual(self.client.post(f'/api/captions/{pid}/render',json={'preview':True}).status_code,202)
        self.assertTrue(self.wait(pid)['last_render'])

    def test_alignment_failure_success_and_cancellation_preserve_saved_text(self):
        response=self.client.post('/api/captions',data={'video':(io.BytesIO(self.source.read_bytes()),'sample.mp4')})
        pid = self.j(response)['id']
        data = self.wait(pid)
        data['cues']=[dict(start=.2,end=1,text='Keep me',words=[])]
        self.client.put('/api/captions/'+pid,json=data)
        options=dict(text='Hello world',language='en',start=.2,end=1.8)
        self.assertEqual(self.client.post(f'/api/captions/{pid}/align',json={**options,'language':''}).status_code,400)
        result={'segments':[{'words':[dict(word='Hello',start=.1,end=.5),dict(word=' world',start=.6,end=1)]}]}
        with patch('captions.align_lyrics',side_effect=ValueError('Cannot align')):
            self.client.post(f'/api/captions/{pid}/align',json=options)
            self.assertEqual(self.wait(pid,'error')['cues'][0]['text'],'Keep me')
        with patch('captions.align_lyrics',return_value=result):
            self.client.post(f'/api/captions/{pid}/align',json=options)
            data=self.wait(pid)
            self.assertEqual(data['timing'],'aligned')
            self.assertAlmostEqual(data['cues'][0]['start'],.3)
            self.assertEqual(data['cues'][0]['text'],'Hello world')
        entered,release=threading.Event(),threading.Event()
        def blocked(*args):
            entered.set();release.wait(5);return result
        with patch('captions.align_lyrics',side_effect=blocked):
            self.client.post(f'/api/captions/{pid}/align',json=options)
            try:
                self.assertTrue(entered.wait(5));job_process.cancel_all()
            finally: release.set()
            self.assertEqual(self.wait(pid,'error')['cues'],data['cues'])
        self.assertFalse((self.root/'library'/'Caption Projects'/pid/'alignment.wav').exists())

    def test_lyric_proposal_review_apply_discard_and_stale_guard(self):
        pid, before = self.karaoke_project()
        options = dict(text='Hello world\nΓεια σου', language='en', review=True,
                       revision=before['revision'])
        self.assertEqual(self.client.post(f'/api/captions/{pid}/correct-lyrics', json=options).status_code, 202)
        proposed = self.wait(pid)
        self.assertEqual(proposed['cues'], before['cues'])
        proposal = proposed['lyric_proposal']
        endpoint = f'/api/captions/{pid}/lyric-proposal'
        self.assertEqual(self.client.post(endpoint, json=dict(id=proposal['id'], revision=-1, action='apply')).status_code, 409)
        applied = self.client.post(endpoint, json=dict(id=proposal['id'], revision=proposed['revision'], action='apply'))
        self.assertEqual(applied.status_code, 200)
        self.assertNotIn('lyric_proposal', applied.json)
        self.assertEqual(applied.json['karaoke_backup']['cues'], before['cues'])
        self.assertEqual(applied.json['cues'], proposal['cues'])
        options['revision'] = applied.json['revision']
        self.client.post(f'/api/captions/{pid}/correct-lyrics', json=options)
        proposed = self.wait(pid)
        proposed['cues'][0]['text'] = 'Edited after proposal'
        proposed['cues'][0]['words'] = []
        updated = self.client.put(f'/api/captions/{pid}', json=proposed).json
        payload = dict(id=proposed['lyric_proposal']['id'], revision=updated['revision'], action='apply')
        self.assertEqual(self.client.post(endpoint, json=payload).status_code, 409)
        discarded = self.client.post(endpoint, json={**payload, 'action':'discard'})
        self.assertEqual(discarded.status_code, 200)
        self.assertEqual(discarded.json['cues'][0]['text'], 'Edited after proposal')

    def test_sectioned_lyric_sync_resume_keeps_completed_sections_and_saved_captions(self):
        pid, before = self.karaoke_project()
        options = dict(text='Hello\nworld', language='en', start=0, end=2,
                       review=True, sections=True, revision=before['revision'])
        coarse = {'segments':[{'words':[dict(word='Hello',start=.1,end=.8),dict(word='world',start=1,end=1.8)]}]}
        entered, release = threading.Event(), threading.Event()
        calls = []
        def refine(model, samples, text, language):
            calls.append(text)
            if text == 'world':
                entered.set(); release.wait(5)
            return {'segments':[{'words':[dict(word=text,start=.05,end=.5)]}]}
        with patch('captions.align_lyrics', return_value=coarse), patch('captions.align_caption_words', side_effect=refine):
            self.client.post(f'/api/captions/{pid}/align', json=options)
            try:
                self.assertTrue(entered.wait(5)); job_process.cancel_all()
            finally:
                release.set()
            failed = self.wait(pid, 'error')
        self.assertEqual(failed['cues'], before['cues'])
        progress = self.root/'library'/'Caption Projects'/pid/'lyric-sync-progress.json'
        self.assertEqual(json.loads(progress.read_text())['completed'], 1)
        with patch('captions.align_lyrics') as first_pass, patch('captions.align_caption_words', side_effect=refine) as refined:
            self.client.post(f'/api/captions/{pid}/align', json={**options, 'resume':True})
            proposed = self.wait(pid)
            first_pass.assert_not_called()
            self.assertEqual(refined.call_count, 1)
            self.assertEqual(refined.call_args.args[2], 'world')
        self.assertEqual(proposed['cues'], before['cues'])
        self.assertEqual([c['text'] for c in proposed['lyric_proposal']['cues']], ['Hello','world'])
        self.client.post(f'/api/captions/{pid}/align', json={**options, 'revision':proposed['revision'], 'resume':True, 'text':'Different'})
        stale = self.wait(pid, 'error')
        self.assertIn('changed', stale['status'])
        self.assertEqual(stale['cues'], before['cues'])

    def test_section_refinement_failure_retains_first_pass_for_review(self):
        pid, before = self.karaoke_project()
        coarse = {'segments':[{'words':[dict(word='Bonjour',start=.2,end=.8)]}]}
        with patch('captions.align_lyrics', return_value=coarse), patch('captions.align_caption_words', side_effect=ValueError('No anchors')):
            self.client.post(f'/api/captions/{pid}/align', json=dict(text='Bonjour', language='fr', start=0, end=2, sections=True, review=True))
            result = self.wait(pid)
        self.assertEqual(result['cues'], before['cues'])
        cue = result['lyric_proposal']['cues'][0]
        self.assertEqual(cue['start'], .2)
        self.assertEqual(cue['karaoke']['state'], 'review')
        self.assertIn('First-pass timing retained', cue['karaoke']['note'])

    def test_correct_lyrics_endpoint_and_backup(self):
        pid, data = self.karaoke_project()
        data['cues'] = [
            dict(start=0.2, end=1.0, text='Helo wrld', words=[]),
            dict(start=1.2, end=2.0, text='Gudbye', words=[])
        ]
        self.client.put('/api/captions/' + pid, json=data)
        correct_text = 'Hello world\nGoodbye'
        res = self.client.post(f'/api/captions/{pid}/correct-lyrics', json=dict(text=correct_text, language='en'))
        self.assertEqual(res.status_code, 202)
        after = self.wait(pid)
        self.assertEqual(after['timing'], 'aligned')
        self.assertEqual(len(after['cues']), 2)
        self.assertEqual(after['cues'][0]['text'], 'Hello world')
        self.assertEqual(after['cues'][1]['text'], 'Goodbye')
        self.assertEqual(after['cues'][0]['start'], 0.2)
        self.assertEqual(after['cues'][0]['end'], 1.0)
        # Verify backup was saved
        self.assertIn('karaoke_backup', after)
        self.assertEqual(after['karaoke_backup']['cues'][0]['text'], 'Helo wrld')
        # Restore karaoke/lyrics backup
        restore = self.client.post(f'/api/captions/{pid}/restore-karaoke', json=dict(revision=after['revision']))
        self.assertEqual(restore.status_code, 200)
        restored = self.j(restore)
        self.assertEqual(restored['cues'][0]['text'], 'Helo wrld')

    def test_multilingual_karaoke_and_overrides(self):
        pid,data=self.karaoke_project()
        data['cues']=[dict(start=.1,end=.9,text='Bonjour mon amour',words=[]),dict(start=1,end=1.9,text='사랑해 hello',words=[])]
        data = self.j(self.client.put('/api/captions/' + pid, json=data))
        languages=[]
        def align(model,audio,text,language):
            languages.append(language)
            words=text.split()
            return {'segments':[{'words':[dict(word=w,start=.05+i*.2,end=.2+i*.2) for i,w in enumerate(words)]}]}
        with patch('captions.detect_caption_language',return_value='fr') as detect, patch('captions.align_caption_words',side_effect=align):
            self.client.post(f'/api/captions/{pid}/karaoke',json=dict(revision=data['revision'],language='en-fr-ko'))
            after=self.wait(pid)
            self.assertEqual(languages,['fr','ko'])
            self.assertEqual(detect.call_args.args[2],('en','fr','ko'))
            self.assertTrue(all(c['karaoke']['state']=='review' for c in after['cues']))
            self.client.post(f'/api/captions/{pid}/karaoke',json=dict(revision=after['revision'],language='ko',index=1))
            self.wait(pid)
            self.assertEqual(languages[-1],'ko')
        self.assertEqual([c['text'] for c in after['cues']],[c['text'] for c in data['cues']])

    def test_lyric_range_preserves_other_captions_and_rejects_partial_lines(self):
        pid,data=self.karaoke_project()
        data['cues']=[dict(start=.1,end=.8,text='Hello there',words=[]),
                      dict(start=1,end=1.9,text='Keep this line',words=[])]
        data=self.j(self.client.put('/api/captions/'+pid,json=data))
        invalid=self.client.post(f'/api/captions/{pid}/correct-lyrics',json=dict(text='Hello world',start=.3,end=.9))
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(self.client.get('/api/captions/'+pid).json['cues'],data['cues'])
        self.client.post(f'/api/captions/{pid}/correct-lyrics',json=dict(text='Hello world',start=0,end=.9))
        after=self.wait(pid)
        self.assertEqual(after['cues'][0]['text'],'Hello world')
        self.assertEqual(after['cues'][1],data['cues'][1])
        aligned={'segments':[{'words':[dict(word='Bonjour',start=.1,end=.7)]}]}
        with patch('captions.align_lyrics',return_value=aligned):
            self.client.post(f'/api/captions/{pid}/align',json=dict(text='Bonjour',language='fr',start=0,end=.9))
            after=self.wait(pid)
        self.assertEqual(after['cues'][0]['text'],'Bonjour')
        self.assertEqual(after['cues'][1],data['cues'][1])

    def test_interrupted_karaoke_resumes_completed_lines_without_replacing_edits(self):
        pid,before=self.karaoke_project()
        entered,release=threading.Event(),threading.Event()
        calls=[]
        def result(text):
            return {'segments':[{'words':[dict(word=w,start=.05+i*.25,end=.2+i*.25) for i,w in enumerate(text.split())]}]}
        def align(model,audio,text,language):
            calls.append(text)
            if len(calls)==2:
                entered.set();release.wait(5)
            return result(text)
        with patch('captions.align_caption_words',side_effect=align):
            self.client.post(f'/api/captions/{pid}/karaoke',json=dict(revision=before['revision'],language='auto'))
            try:
                self.assertTrue(entered.wait(5));job_process.cancel_all()
            finally:
                release.set()
            cancelled=self.wait(pid,'error')
        self.assertEqual(cancelled['cues'],before['cues'])
        progress_path=self.root/'library'/'Caption Projects'/pid/'karaoke-progress.json'
        interrupted_progress=progress_path.read_bytes()
        with patch('captions.align_caption_words',side_effect=lambda m,a,t,l:result(t)) as resumed:
            self.client.post(f'/api/captions/{pid}/karaoke',json=dict(revision=cancelled['revision'],language='auto',resume=True))
            after=self.wait(pid)
        self.assertEqual(resumed.call_count,1)
        self.assertAlmostEqual(after['cues'][0]['words'][0]['start'],.15)
        self.assertEqual([c['text'] for c in after['cues']],[c['text'] for c in before['cues']])
        progress_path.write_bytes(interrupted_progress)
        after['cues'][0].update(text='Edited words',words=[])
        edited=self.j(self.client.put('/api/captions/'+pid,json=after))
        self.client.post(f'/api/captions/{pid}/karaoke',json=dict(revision=edited['revision'],language='auto',resume=True))
        rejected=self.wait(pid,'error')
        self.assertEqual(rejected['cues'],edited['cues'])
        self.assertIn('changed',rejected['status'])

    def test_composition_edit_trim_restore_duplicate_and_originals(self):
        import creator_composition as comp
        pid,before=self.karaoke_project()
        folder=self.root/'library'/'Caption Projects'/pid
        original=(folder/'original.mp4').read_bytes()
        legacy=copy.deepcopy(before);legacy.pop('studio');(folder/'project.json').write_text(json.dumps(legacy),encoding='utf-8')
        settings={**before['studio']['settings'], 'shape':'square','start':.2,'end':1.8,'offset':.2,
                  'fit':'fit','blur':1,'dim':.1,'opacity':.1,'zoom':.05,'fade_in':.1,'fade_out':.1,'background_volume':.2}
        response=self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=before['revision'],settings=json.dumps(settings)))
        self.assertEqual(response.status_code,202,response.json)
        after=self.wait(pid)
        self.assertEqual(after['studio']['version'],1)
        self.assertEqual(after['style'],before['style'])
        self.assertEqual(after['cues'][0],before['cues'][0])
        self.assertAlmostEqual(after['cues'][-1]['end'],1.8)
        self.assertEqual(after['cues'][-1]['karaoke']['state'],'review')
        self.assertEqual(after['width'],1080)
        self.assertEqual(after['height'],1080)
        self.assertEqual((folder/'original.mp4').read_bytes(),original)
        self.assertTrue((folder/'pre-studio-project.json').is_file())
        self.assertEqual(self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=before['revision'],settings=json.dumps(settings))).status_code,409)
        with self.client.get(f'/api/captions/{pid}/media/{after["preview"]}') as r: self.assertEqual(r.status_code,200)
        duplicate = self.j(self.client.post(f'/api/captions/{pid}/duplicate', json=dict(revision=after['revision'])))
        self.assertNotEqual(duplicate['id'],pid)
        self.assertEqual(duplicate['cues'],after['cues'])
        self.assertTrue((folder.parent/duplicate['id']/duplicate['preview']).is_file())
        restored = self.j(self.client.post(f'/api/captions/{pid}/restore-composition', json=dict(revision=after['revision'])))
        self.assertEqual(restored['source'],before['source'])
        self.assertEqual(restored['cues'],before['cues'])
        self.assertEqual(restored['peaks'],before['peaks'])
        self.client.post(f'/api/captions/{pid}/render',json=dict(preview=True))
        self.assertTrue(self.wait(pid)['last_render'])

    def test_background_replace_relink_and_failed_composition_keeps_project(self):
        from PIL import Image
        pid,before=self.karaoke_project()
        image=io.BytesIO();Image.new('RGB',(120,80),'red').save(image,format='PNG')
        settings={**before['studio']['settings'],'shape':'landscape','visualizer':True}
        response=self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=before['revision'],settings=json.dumps(settings),background=(io.BytesIO(image.getvalue()),'new.png')))
        self.assertEqual(response.status_code,202,response.json)
        after=self.wait(pid)
        self.assertEqual(after['cues'],before['cues'])
        self.assertEqual(after['studio']['assets']['background']['kind'],'image')
        folder=self.root/'library'/'Caption Projects'/pid
        (folder/after['studio']['assets']['background']['file']).unlink()
        loaded = self.j(self.client.get('/api/captions/' + pid))
        self.assertEqual(loaded['missing_assets'],['background'])
        response=self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=after['revision'],settings=json.dumps(settings)))
        self.assertEqual(response.status_code,400)
        response=self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=after['revision'],settings=json.dumps(settings),background=(io.BytesIO(image.getvalue()),'relinked.png')))
        after=self.wait(pid)
        self.assertEqual(after['missing_assets'],[])
        response=self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=after['revision'],settings=json.dumps(settings),audio=(io.BytesIO(b'not audio'),'bad.wav')))
        failed=self.wait(pid,'error')
        for key in ('source','preview','studio','cues','duration','peaks'): self.assertEqual(failed[key],after[key])
        self.assertFalse(list(folder.glob('duration_*.wav')))

    def test_pasted_lyrics_partial_timing_replaces_text_and_keeps_restore_point(self):
        pid,before=self.karaoke_project()
        result={'segments':[{'words':[dict(word='Καλή',start=.1,end=.4),dict(word='μέρα',start=.4,end=.4),dict(word='ξανά',start=1,end=1.5)]}]}
        with patch('captions.align_lyrics',return_value=result):
            response=self.client.post(f'/api/captions/{pid}/align',json=dict(text='Καλή μέρα\nξανά',language='el',start=0,end=2))
            self.assertEqual(response.status_code,202,response.json)
            after=self.wait(pid)
        self.assertEqual([c['text'] for c in after['cues']],['Καλή μέρα','ξανά'])
        self.assertEqual(after['cues'][0]['karaoke']['state'],'review')
        self.assertEqual(after['karaoke_backup']['cues'],before['cues'])
        self.assertEqual(after['style'],before['style'])

    def test_composition_delay_keeps_rendered_audio_and_words_synchronized(self):
        import numpy as np
        pid,before=self.karaoke_project()
        settings={**before['studio']['settings'],'offset':.4,'volume':.5,'shape':'square'}
        self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=before['revision'],settings=json.dumps(settings)))
        after=self.wait(pid)
        self.assertAlmostEqual(after['cues'][0]['start'],before['cues'][0]['start']+.4)
        self.assertAlmostEqual(after['duration'],before['duration']+.4)
        media=self.root/'library'/'Caption Projects'/pid/after['source']
        audio=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-i',str(media),'-vn','-ac','1','-ar','1000','-f','f32le','-'],capture_output=True,check=True)
        samples=np.frombuffer(audio.stdout,dtype='<f4')
        self.assertLess(float(np.max(np.abs(samples[:250]))),.002)
        self.assertGreater(float(np.max(np.abs(samples[500:1000]))),.01)

    def test_composition_cancel_is_transactional(self):
        pid,before=self.karaoke_project()
        entered,release=threading.Event(),threading.Event()
        from creator_composition import render_args
        def delayed(*args, **kwargs):
            entered.set();release.wait(5);job_process.check_cancelled();return render_args(*args, **kwargs)
        with patch('captions.composition_model.render_args',side_effect=delayed):
            self.client.post(f'/api/captions/{pid}/composition',data=dict(revision=before['revision'],settings=json.dumps(before['studio']['settings'])))
            try:
                self.assertTrue(entered.wait(5));job_process.cancel_all()
            finally: release.set()
            failed=self.wait(pid,'error')
        for key in ('source','studio','cues','duration','peaks'): self.assertEqual(failed[key],before[key])
        self.assertNotIn('composition_backup',failed)

    def setUp(self):
        artifacts=Path(__file__).resolve().parents[1]/'audit_artifacts'
        artifacts.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=artifacts)
        self.root=Path(self.temp.name)
        self.source=self.root/'source.mp4'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-f','lavfi','-i','color=blue:size=320x240:rate=10',
                        '-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','libx264','-c:a','aac',str(self.source)],capture_output=True,check=True)
        class Model:
            def transcribe(self, path, **options):
                assert options['word_timestamps']
                return {'segments':[{'start':.1,'end':1.5,'text':'Hello world','words':[
                    {'start':.1,'end':.6,'word':'Hello'},{'start':.8,'end':1.5,'word':'world'}]}]}
        app=Flask('caption_test')
        self.model=Model()
        detector=patch('captions.detect_caption_language',return_value='en');detector.start();self.addCleanup(detector.stop)
        register_captions(app,self.root/'library',lambda:None,lambda:None,lambda:None,lambda:self.model,lambda p:False)
        self.client=app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, pid: str, state: str = 'ready') -> dict[str, Any]:
        for _ in range(200):
            res = self.client.get('/api/captions/' + pid)
            data = res.json
            if data and data.get('state') != 'busy':
                self.assertEqual(data.get('state'), state, data.get('status'))
                return data
            time.sleep(.05)
        raise TimeoutError('Caption job timed out')

    def test_upload_save_conflict_transcribe_export_and_original_preserved(self):
        original=self.source.read_bytes()
        response=self.client.post('/api/captions',data={'video':(io.BytesIO(original),'sample.mp4')})
        self.assertEqual(response.status_code,202,response.data)
        pid = self.j(response)['id']
        data = self.wait(pid)
        self.assertEqual((data['width'],data['height']),(320,240))
        self.assertTrue(data['peaks'])
        response=self.client.post(f'/api/captions/{pid}/transcribe',json={'language':'en'})
        self.assertEqual(response.status_code,202)
        data=self.wait(pid)
        self.assertEqual(len(data['cues'][0]['words']),2)
        payload={'revision':data['revision'],'cues':data['cues'],'style':{**data['style'],'karaoke':True}}
        self.assertEqual(self.client.put('/api/captions/'+pid,json=payload).status_code,200)
        self.assertEqual(self.client.put('/api/captions/'+pid,json=payload).status_code,409)
        response=self.client.post(f'/api/captions/{pid}/render',json={'preview':False})
        self.assertEqual(response.status_code,202)
        data=self.wait(pid)
        folder=self.root/'library'/'Caption Projects'/pid
        self.assertEqual((folder/'original.mp4').read_bytes(),original)
        self.assertGreater((folder/data['last_render']).stat().st_size,1000)
        with self.client.get(f'/api/captions/{pid}/media/{data["last_render"]}') as response:
            self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get(f'/api/captions/{pid}/media/project.json').status_code,404)
        with self.client.get(f'/api/captions/{pid}/srt') as response:
            self.assertIn(b'Hello world',response.data)

    def test_arbitrary_path_is_rejected(self):
        response=self.client.post('/api/captions',data={'path':str(self.source)})
        self.assertEqual(response.status_code,400)
        response=self.client.post('/api/captions',data={'audio':(io.BytesIO(b'fake'),'song.wav'),'background_path':str(self.source)})
        self.assertEqual(response.status_code,400)

    def test_cancelled_transcription_keeps_saved_captions(self):
        response=self.client.post('/api/captions',data={'video':(io.BytesIO(self.source.read_bytes()),'sample.mp4')})
        pid = self.j(response)['id']
        data = self.wait(pid)
        payload={'revision':data['revision'],'cues':[dict(start=0,end=1,text='Keep this',words=[])],'style':DEFAULT_STYLE}
        self.assertEqual(self.client.put('/api/captions/'+pid,json=payload).status_code,200)
        entered, release = threading.Event(), threading.Event()
        def inference(*args, **kwargs):
            entered.set()
            release.wait(5)
            return {'segments':[]}
        with patch.object(self.model,'transcribe',side_effect=inference):
            self.client.post(f'/api/captions/{pid}/transcribe',json={'language':'en'})
            try:
                self.assertTrue(entered.wait(5))
                job_process.cancel_all()
            finally:
                release.set()
            data=self.wait(pid,'error')
        self.assertIn('Cancelled',data['status'])
        self.assertEqual(data['cues'][0]['text'],'Keep this')

    def test_restart_reports_interrupted_job_without_losing_captions(self):
        response=self.client.post('/api/captions',data={'video':(io.BytesIO(self.source.read_bytes()),'sample.mp4')})
        pid = self.j(response)['id']
        data = self.wait(pid)
        data.update(state='busy',cues=[dict(start=0,end=1,text='Saved before restart',words=[])])
        location=self.root/'library'/'Caption Projects'/pid/'project.json'
        location.write_text(json.dumps(data),encoding='utf-8')
        restarted=Flask('restarted')
        register_captions(restarted,self.root/'library',lambda:None,lambda:None,lambda:None,lambda:self.model,lambda p:False)
        data = self.j(restarted.test_client().get('/api/captions/' + pid))
        self.assertEqual(data['state'],'error')
        self.assertIn('interrupted',data['status'])
        self.assertEqual(data['cues'][0]['text'],'Saved before restart')

    def test_stock_browser_search_download_and_provenance_in_composition(self):
        # 1. Save Pexels API key and verify status
        keys_res = self.j(self.client.post('/api/captions/stock/keys', json={'pexels': 'px-secret-123'}))
        self.assertTrue(keys_res['pexels'])
        self.assertFalse(keys_res['pixabay'])

        # 2. Search stock via mocked search_stock
        fake_item = dict(
            id='777',
            provider='pexels',
            kind='video',
            title='Pexels video #777 (2s)',
            duration=2.0,
            width=320,
            height=240,
            preview_url='https://images.pexels.com/videos/777/thumb.jpg',
            download_url='https://videos.pexels.com/video-files/777/hd.mp4',
            creator='Elena Visuals',
            source_url='https://www.pexels.com/video/777/',
            license='Pexels License',
            attribution='Video by Elena Visuals on Pexels'
        )
        with patch('captions.composition_model.search_stock', return_value=[fake_item]) as mock_search:
            search_res = self.j(self.client.post('/api/captions/stock/search', json={
                'provider': 'pexels', 'query': 'sunset beach', 'kind': 'video', 'orientation': 'portrait'
            }))
            self.assertEqual(len(search_res['results']), 1)
            self.assertEqual(mock_search.call_args.kwargs['api_key'], 'px-secret-123')

        # 3. Download stock video (mocking download_stock_asset to write self.source bytes)
        def fake_dl(url, provider, kind, dest, check_cancel=None):
            dest.write_bytes(self.source.read_bytes())
            return dest
        with patch('captions.composition_model.download_stock_asset', side_effect=fake_dl):
            dl_res = self.j(self.client.post('/api/captions/stock/download', json=fake_item))
        self.assertTrue(Path(dl_res['path']).is_file())
        self.assertEqual(dl_res['provenance']['creator'], 'Elena Visuals')
        self.assertEqual(dl_res['provenance']['license'], 'Pexels License')

        # 4. Apply downloaded stock background in composition and verify provenance is retained
        pid, before = self.karaoke_project()
        settings = {**before['studio']['settings'], 'shape': 'portrait'}
        comp_res = self.client.post(f'/api/captions/{pid}/composition', data={
            'revision': before['revision'],
            'settings': json.dumps(settings),
            'background_path': dl_res['path'],
            'stock_provenance': json.dumps(dl_res['provenance'])
        })
        self.assertEqual(comp_res.status_code, 202, comp_res.json)
        after = self.wait(pid)
        bg_asset = after['studio']['assets']['background']
        self.assertEqual(bg_asset['kind'], 'video')
        self.assertEqual(bg_asset['provenance']['creator'], 'Elena Visuals')
        self.assertEqual(bg_asset['provenance']['license'], 'Pexels License')
        self.assertEqual(bg_asset['provenance']['source_url'], 'https://www.pexels.com/video/777/')

    def test_phase5_multitrack_broll_title_card_and_render_quality_presets(self):
        from PIL import Image
        pid, before = self.karaoke_project()
        broll_img = io.BytesIO()
        Image.new('RGB', (160, 160), 'cyan').save(broll_img, format='PNG')
        settings = {
            **before['studio']['settings'],
            'brightness': 0.05,
            'contrast': 1.1,
            'saturation': 1.1,
            'transition_in': 0.2,
            'transition_out': 0.2,
            'keyframe_end_x': 65,
            'keyframe_end_y': 40,
            'title_text': 'Φταίω Εγώ · Intro',
            'title_duration': 1.0,
            'broll_start': 0.2,
            'broll_duration': 1.0,
            'broll_scale': 40,
            'broll_opacity': 0.9,
            'broll_fade': 0.2,
            'background_volume': 0.4,
            'ducking': True,
        }
        res = self.client.post(f'/api/captions/{pid}/composition', data={
            'revision': before['revision'],
            'settings': json.dumps(settings),
            'broll': (io.BytesIO(broll_img.getvalue()), 'cutaway.png')
        })
        self.assertEqual(res.status_code, 202, res.json)
        after = self.wait(pid)
        self.assertIn('broll', after['studio']['assets'])
        self.assertEqual(after['studio']['settings']['title_text'], 'Φταίω Εγώ · Intro')
        self.assertEqual(len(after['studio']['tracks'][3]['clips']), 2)

        # Verify ASS output includes Layer 1 Title Card dialogue event
        ass = ass_text(after)
        self.assertIn('Φταίω Εγώ · Intro', ass)
        self.assertTrue(any(line.startswith('Dialogue: 1,') for line in ass.splitlines()))

        # Render with 'draft' quality preset
        r_draft = self.client.post(f'/api/captions/{pid}/render', json={'preview': True, 'quality': 'draft'})
        self.assertEqual(r_draft.status_code, 202)
        rendered = self.wait(pid)
        self.assertTrue(rendered['last_render'])

    def test_capcut_video_and_audio_effects_in_style_and_composition_render(self):
        pid, before = self.karaoke_project()
        # 1. Apply video filters & audio effects directly via live style panel and render
        fx_style = {
            **before['style'],
            'animation': 'slide_up',
            'glow': 4.0,
            'video_filter': 'sepia',
            'vignette': True,
            'film_grain': 6,
            'sharpen': 0.5,
            'chromatic': 2,
            'noise_cancel': True,
            'voice_isolation': True,
            'audio_effect': 'slowed_reverb',
        }
        saved = self.j(self.client.put(f'/api/captions/{pid}', json={
            'revision': before['revision'],
            'cues': before['cues'],
            'style': fx_style,
            'timing': before['timing'],
        }))
        self.assertEqual(saved['style']['video_filter'], 'sepia')
        self.assertEqual(saved['style']['animation'], 'slide_up')
        self.assertEqual(saved['style']['glow'], 4.0)
        self.assertTrue(saved['style']['voice_isolation'])
        self.assertEqual(saved['style']['audio_effect'], 'slowed_reverb')
        ass_out = ass_text(saved)
        self.assertIn(r'\move(', ass_out)
        self.assertIn(r'\blur4.0', ass_out)

        r_fx = self.client.post(f'/api/captions/{pid}/render', json={'preview': True, 'quality': 'draft'})
        self.assertEqual(r_fx.status_code, 202, r_fx.json)
        after_render = self.wait(pid)
        self.assertEqual(after_render['state'], 'ready')
        self.assertTrue((self.root / 'library' / 'Caption Projects' / pid / after_render['last_render']).is_file())

        # 2. Apply composition-level video filter & audio effect and verify sync to style
        comp_settings = {
            **after_render['studio']['settings'],
            'video_filter': 'cyberpunk',
            'vignette': True,
            'noise_cancel': True,
            'audio_effect': 'concert_hall',
        }
        c_res = self.client.post(f'/api/captions/{pid}/composition', data={
            'revision': after_render['revision'],
            'settings': json.dumps(comp_settings),
        })
        self.assertEqual(c_res.status_code, 202, c_res.json)
        after_comp = self.wait(pid)
        self.assertEqual(after_comp['style']['video_filter'], 'cyberpunk')
        self.assertEqual(after_comp['style']['audio_effect'], 'concert_hall')
        self.assertTrue(after_comp['style']['noise_cancel'])

        # 3. Apply a multi-clip video sequence (existing background + 2 uploaded clips) and verify stitched render
        multi_settings = {
            **after_comp['studio']['settings'],
            'sequence': [
                dict(asset='background', name='Clip 1', duration=0),
                dict(upload_index=0, name='Clip 2 Video', duration=0),
                dict(upload_index=1, name='Clip 3 Video', duration=0),
            ],
        }
        m_res = self.client.post(f'/api/captions/{pid}/composition', data={
            'revision': after_comp['revision'],
            'settings': json.dumps(multi_settings),
            'clip_files': [
                (io.BytesIO(self.source.read_bytes()), 'clip2.mp4'),
                (io.BytesIO(self.source.read_bytes()), 'clip3.mp4'),
            ],
        }, content_type='multipart/form-data')
        self.assertEqual(m_res.status_code, 202, m_res.json)
        after_multi = self.wait(pid)
        self.assertEqual(after_multi['state'], 'ready')
        self.assertEqual(len(after_multi['studio']['settings']['sequence']), 3)
        self.assertEqual(len(after_multi['studio']['tracks'][0]['clips']), 3)
        self.assertTrue((self.root / 'library' / 'Caption Projects' / pid / after_multi['source']).is_file())

    def test_zoom_in_and_typewriter_motion_presets_in_ass(self):
        project = {
            'cues': [dict(start=0.0, end=2.0, text='Hello world', words=[])],
            'style': {**DEFAULT_STYLE, 'animation': 'zoom_in'},
            'width': 1080,
            'height': 1920,
        }
        ass_zoom = ass_text(project)
        self.assertIn(r'\fscx70\fscy70\t(0,200,\fscx100\fscy100)', ass_zoom)

        project['style']['animation'] = 'typewriter'
        ass_typewriter = ass_text(project)
        self.assertIn('Dialogue: 0,00:00:00.00', ass_typewriter)
        self.assertIn('Hello world', ass_typewriter)
        lines = [line for line in ass_typewriter.splitlines() if line.startswith('Dialogue: 0,')]
        self.assertGreater(len(lines), 3)

        project_words = {
            'cues': [dict(start=0.0, end=2.0, text='Singing a song', words=[
                dict(start=0.0, end=0.6, text='Singing'),
                dict(start=0.6, end=1.2, text='a'),
                dict(start=1.2, end=2.0, text='song'),
            ])],
            'style': {**DEFAULT_STYLE, 'animation': 'typewriter', 'karaoke': True},
            'width': 1080,
            'height': 1920,
        }
        ass_words_tw = ass_text(project_words)
        word_lines = [line for line in ass_words_tw.splitlines() if line.startswith('Dialogue: 0,')]
        self.assertGreater(len(word_lines), 3)
        self.assertNotIn('Singing', word_lines[0])
        self.assertIn('Singing', '\n'.join(word_lines))
        self.assertNotIn('song', word_lines[0])
        self.assertIn('song', word_lines[-1])

    def test_custom_font_upload_validation_and_render_presets(self):
        from captions import CUSTOM_FONT_DIR, CUSTOM_FONTS, refresh_custom_fonts
        # 1. GET /api/captions/fonts
        res = self.client.get('/api/captions/fonts')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('bundled', data)
        self.assertIn('Montserrat', data['bundled'])
        self.assertIn('custom', data)

        # 2. Reject missing file
        bad_res1 = self.client.post('/api/captions/fonts/upload', data={})
        self.assertIn(bad_res1.status_code, (400, 500))

        # 3. Reject invalid extension
        bad_res2 = self.client.post('/api/captions/fonts/upload', data={
            'font_file': (io.BytesIO(b'not a font'), 'malicious.exe')
        })
        self.assertIn(bad_res2.status_code, (400, 500))

        # 4. Reject corrupt magic bytes
        bad_res3 = self.client.post('/api/captions/fonts/upload', data={
            'font_file': (io.BytesIO(b'corrupt_content_not_real_ttf'), 'bad.ttf')
        })
        self.assertIn(bad_res3.status_code, (400, 500))

        # 5. Upload valid font
        real_ttf = FONT_DIR / 'Bangers-Regular.ttf'
        self.assertTrue(real_ttf.is_file())
        raw_bytes = real_ttf.read_bytes()
        test_font_name = 'Test_Custom_Bangers.ttf'
        up_res = self.client.post('/api/captions/fonts/upload', data={
            'font_file': (io.BytesIO(raw_bytes), test_font_name)
        })
        self.assertEqual(up_res.status_code, 200, up_res.data)
        up_data = up_res.get_json()
        self.assertTrue(up_data.get('success'))
        family = up_data.get('family')
        self.assertTrue(family)
        custom_file = CUSTOM_FONT_DIR / up_data.get('filename')
        try:
            self.assertTrue(custom_file.is_file())
            self.assertIn(family, CUSTOM_FONTS)
            conflict=self.client.post('/api/captions/fonts/upload',data={
                'font_file':(io.BytesIO(raw_bytes+b'\0'),'same-family.ttf')})
            self.assertEqual(conflict.status_code,400)
            self.assertEqual(custom_file.read_bytes(),raw_bytes)
            served=self.client.get(up_data['url'])
            self.assertEqual(served.status_code,200)
            self.assertEqual(served.data,raw_bytes)
            served.close()

            # 6. Verify font is returned in font list
            list_res = self.client.get('/api/captions/fonts')
            families = [f['family'] for f in list_res.get_json()['custom']]
            self.assertIn(family, families)

            # 7. Render with the new custom font and 60fps & 4k quality presets
            pid, before = self.karaoke_project()
            custom_style = {**before['style'], 'font': family}
            self.client.put(f'/api/captions/{pid}', json={
                'revision': before['revision'],
                'cues': before['cues'],
                'style': custom_style,
                'timing': before['timing'],
            })
            r_60 = self.client.post(f'/api/captions/{pid}/render', json={'preview': True, 'quality': '60fps'})
            self.assertEqual(r_60.status_code, 202)
            done_60 = self.wait(pid)
            self.assertTrue(done_60.get('last_render'))

            r_4k = self.client.post(f'/api/captions/{pid}/render', json={'preview': True, 'quality': '4k'})
            self.assertEqual(r_4k.status_code, 202)
            done_4k = self.wait(pid)
            self.assertTrue(done_4k.get('last_render'))
        finally:
            if custom_file.is_file():
                custom_file.unlink(missing_ok=True)
            refresh_custom_fonts()

    def test_sticker_emoji_and_clip_speed_in_composition(self):
        pid, before = self.karaoke_project()
        settings = {
            **before['studio']['settings'],
            'sticker_start': 0.5,
            'sticker_duration': 2.0,
            'sticker_x': 80,
            'sticker_y': 20,
            'sticker_scale': 35,
            'sticker_opacity': 0.9,
            'sticker_fade': 0.2,
            'sticker_anim': 'pop',
            'sequence': [
                {'asset': 'background', 'name': 'Clip 1 Slow', 'duration': 1.0, 'speed': 0.5},
                {'asset': 'background', 'name': 'Clip 2 Fast', 'duration': 1.0, 'speed': 2.0},
            ]
        }
        res = self.client.post(f'/api/captions/{pid}/composition', data={
            'revision': before['revision'],
            'settings': json.dumps(settings),
            'emoji_sticker': '🔥',
        })
        self.assertEqual(res.status_code, 202, res.json)
        after = self.wait(pid)
        self.assertIn('sticker', after['studio']['assets'])
        self.assertEqual(after['studio']['assets']['sticker']['name'], 'Emoji 🔥')
        overlay_clips = after['studio']['tracks'][3]['clips']
        self.assertTrue(any(c.get('kind') == 'sticker' for c in overlay_clips))
        bg_clips = after['studio']['tracks'][0]['clips']
        self.assertEqual(len(bg_clips), 2)
        self.assertEqual(bg_clips[0]['speed'], 0.5)
        self.assertEqual(bg_clips[1]['speed'], 2.0)

        # Clear sticker
        clear_res = self.client.post(f'/api/captions/{pid}/composition', data={
            'revision': after['revision'],
            'settings': json.dumps(after['studio']['settings']),
            'clear_sticker': 'true',
        })
        self.assertEqual(clear_res.status_code, 202, clear_res.json)
        after_clear = self.wait(pid)
        self.assertNotIn('sticker', after_clear['studio']['assets'])

    def test_distribute_words_and_validate_edit_submillisecond_float_precision(self):
        """Verify that floating point fractions (e.g. 22.556666666666658 - 26.67666666666666) never cause validation errors."""
        from captions import distribute_words_in_cue, validate_edit
        start = 22.556666666666658
        end = 26.67666666666666
        words_text = ['Stopped', 'checking', 'the', 'phone', 'stopped', 'looking', 'at', 'the', 'door']

        words = distribute_words_in_cue(words_text, start, end)
        self.assertEqual(words[0]['start'], start)
        self.assertEqual(words[-1]['end'], end)
        self.assertTrue(all(start <= w['start'] <= end and start <= w['end'] <= end for w in words))

        # Test validate_edit with exact words
        cue = dict(text=' '.join(words_text), start=start, end=end, words=words)
        validated = validate_edit(dict(cues=[cue]), 300)
        self.assertEqual(len(validated['cues']), 1)
        self.assertEqual(len(validated['cues'][0]['words']), len(words_text))

        # Test validate_edit with slightly noisy / rounded word timestamps
        noisy_words = [
            dict(text='Stopped', start=22.555, end=23.0),      # slightly before start
            dict(text='checking', start=23.0, end=23.5),
            dict(text='the', start=23.5, end=24.0),
            dict(text='phone', start=24.0, end=24.5),
            dict(text='stopped', start=24.5, end=25.0),
            dict(text='looking', start=25.0, end=25.5),
            dict(text='at', start=25.5, end=26.0),
            dict(text='the', start=26.0, end=26.4),
            dict(text='door', start=26.4, end=26.678)          # slightly after end (26.678 > 26.67666666666666)
        ]
        noisy_cue = dict(text=' '.join(words_text), start=start, end=end, words=noisy_words)
        fixed = validate_edit(dict(cues=[noisy_cue]), 300)
        self.assertEqual(fixed['cues'][0]['words'][0]['start'], start)
        self.assertEqual(fixed['cues'][0]['words'][-1]['end'], end)

    def test_detect_face_in_video_and_track_face_endpoint(self):
        """Test OpenCV face detection helper and AR track-face endpoint."""
        import numpy as np
        import cv2
        from captions import detect_face_in_video
        from unittest.mock import MagicMock, patch

        # Nonexistent video returns clean found=False
        res = detect_face_in_video(Path('nonexistent.mp4'), 0.0)
        self.assertFalse(res['found'])

        # Mock video capture and cascade detection
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, frame)
        mock_cap.get.side_effect = lambda prop: 300.0 if prop == cv2.CAP_PROP_FRAME_COUNT else 30.0

        with patch('captions.cv2.VideoCapture', return_value=mock_cap), \
             patch('captions.cv2.CascadeClassifier.detectMultiScale', return_value=[(100, 100, 200, 200)]):
            test_path = Path(self.root / 'library' / 'Caption Projects' / 'dummy.mp4')
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.touch()

            # Target: head
            res_head = detect_face_in_video(test_path, 1.0, target='head')
            self.assertTrue(res_head['found'])
            self.assertEqual(res_head['target'], 'head')
            self.assertEqual(res_head['x'], 31)
            self.assertEqual(res_head['y'], 14)

            # Target: eyes
            res_eyes = detect_face_in_video(test_path, 1.0, target='eyes')
            self.assertTrue(res_eyes['found'])
            self.assertEqual(res_eyes['target'], 'eyes')
            self.assertEqual(res_eyes['x'], 31)
            self.assertEqual(res_eyes['y'], 62)

            # Target: center
            res_center = detect_face_in_video(test_path, 1.0, target='center')
            self.assertTrue(res_center['found'])
            self.assertEqual(res_center['target'], 'center')
            self.assertEqual(res_center['x'], 31)
            self.assertEqual(res_center['y'], 42)

            # Test API endpoint
            pid, _ = self.karaoke_project()
            resp = self.client.post(f'/api/captions/{pid}/track-face', json={'time': 0.5, 'target': 'head'})
            self.assertEqual(resp.status_code, 200)
            data = resp.json
            self.assertTrue(data['found'])
            self.assertEqual(data['x'], 31)
            self.assertEqual(data['y'], 14)

    def test_render_emoji_sticker(self):
        """Verify render_emoji_sticker returns an RGBA image with non-zero alpha or raises clean ValueError."""
        import numpy as np
        from captions import render_emoji_sticker
        try:
            img = render_emoji_sticker('👑', size=256)
            self.assertEqual(img.mode, 'RGBA')
            alpha = np.asarray(img)[..., 3]
            self.assertTrue(alpha.any(), 'Rendered emoji must have non-zero alpha channel')
            self.assertGreater(img.width, 0)
            self.assertGreater(img.height, 0)
        except ValueError as err:
            self.assertIn('No colour emoji font is available', str(err))




