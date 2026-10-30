"""Isolated identity, bilingual layout, translation and export regressions."""
import tests._isolation
import copy
import json
import unittest
import subprocess
import tempfile
from pathlib import Path
import imageio_ffmpeg
from unittest.mock import patch
from tests import test_captions
from assets import lyric_tracks, lyric_translation
from captions import validate_edit, DEFAULT_STYLE, ass_text, layout_rows


class TrackTests(unittest.TestCase):
    def test_mixed_script_layout_uses_explicit_bundled_fallbacks(self):
        text='Hello άνεμος 너의'
        cue=dict(start=0,end=3,text=text,words=[dict(text=t,start=i,end=i+1) for i,t in enumerate(text.split())])
        original=copy.deepcopy(cue)
        style={**DEFAULT_STYLE,'font':'Bangers','layout_enabled':True,'box_width':96,'size':3}
        rows=layout_rows(cue,style,1080,1920)
        runs=[run for row in rows for run in row['runs']]
        self.assertEqual(''.join(run['text'] for run in runs),text)
        self.assertTrue(any(run['font']=='Roboto' and 'ά' in run['text'] for run in runs))
        self.assertTrue(any(run['font']=='Noto Sans KR' and '너' in run['text'] for run in runs))
        self.assertEqual(cue,original)
        script=ass_text(dict(cues=[cue],style=style,width=1080,height=1920))
        self.assertIn(r'\fnRoboto',script)
        self.assertIn(r'\fnNoto Sans KR',script)
        self.assertIn(r'\fnBangers',script)
        for family in ('Lobster','Montserrat','Oswald','Noto Sans KR'):
            greek_cue=dict(start=0,end=3,text='Ανάσα μου πίσω Δεν Ωμέγα',words=[])
            greek_rows=layout_rows(greek_cue,{**style,'font':family},1080,1920)
            greek_runs=[r for row in greek_rows for r in row['runs'] if r['text'].strip()]
            self.assertTrue(all(r['font']=='Roboto' for r in greek_runs), f'{family} split Greek runs: {greek_runs}')

    def test_rendered_background_tracks_fade_zoom_and_slide(self):
        cue=dict(start=0,end=1,text='Hello',words=[])
        for animation in ('fade','zoom_in','slide_up'):
            with self.subTest(animation=animation),tempfile.TemporaryDirectory() as directory:
                style={**DEFAULT_STYLE,'font':'Arial','size':12,'layout_enabled':True,
                       'background':True,'box_padding':2,'box_radius':1,'animation':animation}
                script=ass_text(dict(cues=[cue],width=320,height=180,style=style))
                # Isolate the plate so white text/outline cannot affect geometry measurements.
                script='\n'.join(line for line in script.splitlines() if not line.startswith('Dialogue: 0,'))+'\n'
                Path(directory,'captions.ass').write_text(script,encoding='utf-8')
                pixels=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i',
                    'color=white:size=320x180:rate=20:duration=0.3','-vf','ass=captions.ass',
                    '-pix_fmt','rgb24','-f','rawvideo','-'],cwd=directory,capture_output=True,check=True,timeout=30).stdout
                frame_size=320*180*3
                early=pixels[frame_size:2*frame_size];late=pixels[5*frame_size:6*frame_size]
                def dark_points(frame):
                    return [i//3 for i in range(0,len(frame),3) if frame[i]<220]
                a,b=dark_points(early),dark_points(late)
                self.assertTrue(a);self.assertTrue(b)
                if animation=='fade':
                    self.assertLess(sum(255-v for v in early),sum(255-v for v in late)*.6)
                elif animation=='zoom_in':
                    self.assertLess(len(a),len(b)*.8)
                else:
                    self.assertGreater(sum(p//320 for p in a)/len(a),sum(p//320 for p in b)/len(b)+2)

    def test_word_pop_multiplies_caption_entrance_scale(self):
        cue=dict(start=0,end=1,text='Hi',words=[dict(text='Hi',start=0,end=1)])
        project=dict(cues=[cue],width=320,height=180,style={**DEFAULT_STYLE,'animation':'zoom_in','karaoke':True,'word_pop':True})
        script=ass_text(project)
        self.assertIn(r'\fscx80.5\fscy80.5\t(0,200,\fscx115\fscy115)',script)

    def test_long_words_fit_without_changing_karaoke_tokens(self):
        for text, font in [('Supercalifragilisticexpialidocious','Arial'),
                           ('Καλημέρακαλημέρακαλημέρα','Arial'),
                           ('너의이름을바람에불러도대답이없어','Noto Sans KR')]:
            with self.subTest(font=font,text=text):
                cue=dict(start=0,end=2,text=text,words=[dict(text=text,start=.1,end=1.9)])
                original=copy.deepcopy(cue)
                style={**DEFAULT_STYLE,'font':font,'box_width':25,'box_padding':1,'letter_spacing':.5,'layout_enabled':True}
                result=layout_rows(cue,style,320,568)
                self.assertEqual(len(result),1)
                self.assertTrue(result[0]['fitted'])
                self.assertLessEqual(result[0]['width'],320*.25-2*568*.01+.001)
                self.assertLess(result[0]['letter_spacing'],.5)
                self.assertEqual(result[0]['words'],cue['words'])
                self.assertEqual(cue,original)
                self.assertIn(text,ass_text(dict(cues=[cue],style=style,width=320,height=568)))

    def test_impossible_padding_reports_actionable_layout_error(self):
        cue=dict(start=0,end=2,text='Hello',words=[])
        with self.assertRaisesRegex(ValueError,'padding'):
            layout_rows(cue,{**DEFAULT_STYLE,'box_width':20,'box_padding':4},320,1920)

    def test_rendered_long_word_stays_inside_narrow_box(self):
        cue=dict(start=0,end=1,text='Supercalifragilisticexpialidocious',words=[])
        style={**DEFAULT_STYLE,'font':'Arial','box_width':25,'box_padding':0,'letter_spacing':.2,'layout_enabled':True}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'captions.ass').write_text(ass_text(dict(cues=[cue],width=320,height=568,style=style)),encoding='utf-8')
            pixels=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i',
                'color=black:size=320x568:duration=1','-vf','ass=captions.ass','-frames:v','1',
                '-pix_fmt','rgb24','-f','rawvideo','-'],cwd=directory,capture_output=True,check=True,timeout=30).stdout
        columns=[i//3%320 for i in range(0,len(pixels),3) if max(pixels[i:i+3])>40]
        self.assertTrue(columns,'Rendered caption must be visible')
        self.assertLessEqual(max(columns)-min(columns)+1,90)

    def test_rendered_fade_remains_partial_after_word_boundary(self):
        cue=dict(start=0,end=1,text='Hi there',words=[dict(text='Hi',start=0,end=.08),dict(text='there',start=.08,end=1)])
        style={**DEFAULT_STYLE,'font':'Arial','size':12,'karaoke':True,'highlight':'#ffffff','animation':'fade'}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'captions.ass').write_text(ass_text(dict(cues=[cue],width=320,height=180,style=style)),encoding='utf-8')
            rendered=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i',
                'color=black:size=320x180:rate=20:duration=0.3','-vf','ass=captions.ass',
                '-pix_fmt','rgb24','-f','rawvideo','-'],cwd=directory,capture_output=True,check=True,timeout=30).stdout
        frame_size=320*180*3
        partial=sum(rendered[2*frame_size:3*frame_size])
        complete=sum(rendered[4*frame_size:5*frame_size])
        self.assertGreater(partial,0)
        self.assertLess(partial,complete*.85,'Fade must not jump to full opacity at the .08s word boundary')

    def test_animation_continues_across_karaoke_word_changes(self):
        cue=dict(start=0,end=1,text='Hi there',words=[dict(text='Hi',start=0,end=.08),dict(text='there',start=.08,end=1)])
        project=dict(cues=[cue],width=1080,height=1920,style={**DEFAULT_STYLE,'karaoke':True,'animation':'pop','glow':2})
        events=[line for line in ass_text(project).splitlines() if line.startswith('Dialogue: 0,')]
        self.assertIn(r'\fscx92.5\fscy92.5\t(0,80,\fscx100\fscy100)',events[1])
        self.assertIn(r'{\r\pos(',events[1])
        self.assertIn(r'\blur2.0',events[1])
        project['style']['animation']='slide_up'
        events=[line for line in ass_text(project).splitlines() if line.startswith('Dialogue: 0,')]
        self.assertIn(r'\move(',events[1])
        self.assertIn(',0,100)',events[1])
        project['style']['animation']='fade'
        events=[line for line in ass_text(project).splitlines() if line.startswith('Dialogue: 0,')]
        self.assertIn(r'\alpha&H8E&',events[1])
        project['style'].update(animation='typewriter',karaoke=False)
        events=[line for line in ass_text(project).splitlines() if line.startswith('Dialogue: 0,')]
        self.assertNotIn('there',events[0])

    def test_ids_and_stale_translation_preserve_content(self):
        cues=[dict(start=0,end=2,text='Γεια σου',words=[])]
        lyric_tracks.ensure_ids(cues,'project')
        original=copy.deepcopy(cues)
        lyric_tracks.ensure_ids(cues,'project')
        self.assertEqual(cues,original)
        cues[0]['translations']={'en':dict(text='Hello',source=lyric_tracks.source_hash('Γεια σου'),status='approved',locked=True)}
        saved=validate_edit(dict(cues=cues),2)['cues'][0]
        self.assertEqual(saved['translations']['en']['status'],'approved')
        saved['text']='Καλημέρα'
        changed=validate_edit(dict(cues=[saved]),2)['cues'][0]
        self.assertEqual(changed['translations']['en']['status'],'stale')
        self.assertEqual(changed['translations']['en']['text'],'Hello')
        with self.assertRaises(ValueError): lyric_tracks.export_cues([changed],mode='translation')
        with self.assertRaises(ValueError): validate_edit(dict(cues=[saved,{**saved,'start':2,'end':3}]),3)

    def test_shared_rows_preserve_breaks_timing_and_bilingual_style(self):
        c=dict(start=0,end=2,text='Γεια\nσου',words=[dict(text='Γεια',start=0,end=1),dict(text='σου',start=1,end=2)],
               translations={'en':dict(text='Hello',source=lyric_tracks.source_hash('Γεια\nσου'),status='approved')})
        style={**DEFAULT_STYLE,'layout_enabled':True,'track_mode':'both','line_spacing':1.8,'translation_gap':3,'letter_spacing':.2}
        rows=layout_rows(c,style,1080,1920)
        self.assertEqual([r['text'] for r in rows],['Γεια','σου','Hello'])
        self.assertEqual([r['words'][0]['text'] for r in rows[:2]],['Γεια','σου'])
        self.assertGreater(rows[1]['y']-rows[0]['y'],100)
        ass=ass_text(dict(cues=[c],style=style,width=1080,height=1920,duration=2))
        self.assertIn('Style: Row0,',ass)
        self.assertIn('Hello',ass)
        self.assertIn('Γεια',ass)
        self.assertEqual(lyric_tracks.export_cues([c],mode='both')[0]['text'],'Γεια\nσου\nHello')

    def test_structured_model_output_rejects_duplicates(self):
        payload=dict(lines=[dict(id='one',text='Hello')],context='Hello',target='Greek',model='qwen3-4b-local')
        with patch.object(lyric_translation,'models',return_value=['qwen3-4b-local']),patch.object(lyric_translation,'local_chat',return_value=json.dumps({'lines':[{'id':'wrong','text':'Γεια'}]})):
            with self.assertRaises(ValueError): lyric_translation.translate(**payload)
        with patch.object(lyric_translation,'models',return_value=['qwen3-4b-local']),patch.object(lyric_translation,'local_chat',return_value=json.dumps({'lines':[{'id':'one','text':'Γεια','note':''}]})):
            self.assertEqual(lyric_translation.translate(**payload)['one']['text'],'Γεια')


class TrackWorkflowTests(unittest.TestCase):
    setUp=test_captions.CaptionWorkflowTests.setUp
    tearDown=test_captions.CaptionWorkflowTests.tearDown
    wait=test_captions.CaptionWorkflowTests.wait
    j=test_captions.CaptionWorkflowTests.j
    karaoke_project=test_captions.CaptionWorkflowTests.karaoke_project

    def test_translation_proposal_is_reviewable_and_locked_lines_survive(self):
        pid,data=self.karaoke_project()
        first=data['cues'][0]
        first['translations']={'en':dict(text='Hello world',source=lyric_tracks.source_hash(first['text']),status='approved',locked=True)}
        data['translation_settings']=dict(model='mock',notes='Tender song',glossary='')
        data=self.client.put('/api/captions/'+pid,json=data).json
        def translate(lines,*args):return {line['id']:dict(text='Hello to you',note='Greeting') for line in lines}
        with patch('captions.lyric_translation.translate',side_effect=translate) as model:
            self.assertEqual(self.client.post(f'/api/captions/{pid}/translate',json=dict(revision=data['revision'],language='en')).status_code,202)
            proposed=self.wait(pid)
            self.assertEqual(len(model.call_args.args[0]),1)
        self.assertEqual(proposed['cues'],data['cues'])
        proposal=proposed['translation_proposal']
        applied=self.client.post(f'/api/captions/{pid}/translation-proposal',json=dict(revision=proposed['revision'],id=proposal['id'],action='apply'))
        self.assertEqual(applied.status_code,200)
        self.assertEqual(applied.json['cues'][0]['translations'],data['cues'][0]['translations'])
        self.assertEqual(applied.json['cues'][1]['translations']['en']['text'],'Hello to you')
        with self.client.get(f'/api/captions/{pid}/srt?mode=translation&language=en') as exported:
            self.assertIn(b'Hello to you',exported.data)
        with self.client.get(f'/api/captions/{pid}/ass') as exported:self.assertEqual(exported.status_code,200)
        layout=self.client.post(f'/api/captions/{pid}/layout',json=dict(cue=applied.json['cues'][1],style={**DEFAULT_STYLE,'track_mode':'both'}))
        self.assertEqual(layout.status_code,200)
        self.assertEqual(layout.json['rows'][-1]['text'],'Hello to you')

    def test_bad_model_response_never_changes_saved_captions(self):
        pid,data=self.karaoke_project();data['translation_settings']=dict(model='mock')
        data=self.client.put('/api/captions/'+pid,json=data).json
        with patch('captions.lyric_translation.translate',side_effect=ValueError('Incomplete response')):
            self.client.post(f'/api/captions/{pid}/translate',json=dict(revision=data['revision'],language='en'))
            failed=self.wait(pid,'error')
        self.assertEqual(failed['cues'],data['cues'])
        self.assertNotIn('translation_proposal',failed)

    def test_stale_translation_rejected_and_review_edits_exported(self):
        pid, data = self.karaoke_project()
        data['translation_settings'] = dict(model='mock')
        data = self.client.put('/api/captions/'+pid, json=data).json
        def translate(lines, *args):
            return {line['id']: dict(text='Draft translation', note='') for line in lines}
        def propose(saved):
            with patch('captions.lyric_translation.translate', side_effect=translate):
                self.client.post(f'/api/captions/{pid}/translate', json=dict(revision=saved['revision'], language='en'))
                return self.wait(pid)
        proposed = propose(data)
        old_id = proposed['translation_proposal']['id']
        proposed['cues'][0]['text'] = 'Changed original'
        changed = self.client.put('/api/captions/'+pid, json=proposed).json
        rejected = self.client.post(f'/api/captions/{pid}/translation-proposal', json=dict(
            revision=changed['revision'], id=old_id, action='apply'))
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(self.client.get('/api/captions/'+pid).json['cues'], changed['cues'])
        proposed = propose(changed)
        proposal = proposed['translation_proposal']
        edits = copy.deepcopy(proposal['lines'])
        first_id = proposed['cues'][0]['id']
        edits[first_id].update(text='Reviewed wording', locked=True)
        applied = self.client.post(f'/api/captions/{pid}/translation-proposal', json=dict(
            revision=proposed['revision'], id=proposal['id'], action='apply', lines=edits))
        self.assertEqual(applied.status_code, 200)
        self.assertTrue(applied.json['cues'][0]['translations']['en']['locked'])
        self.assertEqual(applied.json['cues'][0]['text'], 'Changed original')
        with self.client.get(f'/api/captions/{pid}/srt?mode=translation&language=en') as result:
            self.assertIn(b'Reviewed wording', result.data)
            self.assertNotIn(b'Changed original', result.data)

    def test_chorus_consistency_survives_interrupted_job_and_resume(self):
        pid, data = self.karaoke_project()
        texts = ['Chorus', 'Chorus'] + [f'Verse {i}' for i in range(6)] + ['Final verse', 'Chorus']
        data['cues'] = [dict(start=i*.19, end=(i+1)*.19, text=text, words=[])
                        for i, text in enumerate(texts)]
        data['translation_settings'] = dict(model='mock')
        data = self.client.put('/api/captions/'+pid, json=data).json
        calls = []
        def interrupted(lines, *args):
            calls.append(lines)
            if len(calls) == 2:
                raise ValueError('Model interrupted')
            return {line['id']: dict(text='Translated '+line['text'], note='') for line in lines}
        with patch('captions.lyric_translation.translate', side_effect=interrupted):
            self.client.post(f'/api/captions/{pid}/translate', json=dict(revision=data['revision'], language='en'))
            failed = self.wait(pid, 'error')
        self.assertEqual(failed['cues'], data['cues'])
        self.assertEqual(sum(line['text']=='Chorus' for line in calls[0]), 1)
        def resumed(lines, *args):
            self.assertEqual([line['text'] for line in lines], ['Final verse'])
            return {line['id']: dict(text='Ending', note='') for line in lines}
        with patch('captions.lyric_translation.translate', side_effect=resumed) as model:
            self.client.post(f'/api/captions/{pid}/translate', json=dict(revision=failed['revision'], language='en', resume=True))
            ready = self.wait(pid)
            self.assertEqual(model.call_count, 1)
        proposal = ready['translation_proposal']['lines']
        self.assertEqual(len(proposal), 10)
        self.assertEqual({proposal[c['id']]['text'] for c in ready['cues'] if c['text']=='Chorus'}, {'Translated Chorus'})
        self.assertEqual(ready['cues'], data['cues'])
