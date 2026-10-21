"""Caption validation and complete media workflow with real FFmpeg rendering."""
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from flask import Flask
import imageio_ffmpeg
from captions import DEFAULT_STYLE, ass_text, parse_subtitles, register_captions, srt_text, validate_edit, lyric_lines, aligned_cues
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


class CaptionWorkflowTests(unittest.TestCase):
    def karaoke_project(self):
        response=self.client.post('/api/captions',data={'video':(io.BytesIO(self.source.read_bytes()),'sample.mp4')})
        pid=response.json['id'];data=self.wait(pid)
        data['cues']=[dict(start=.1,end=.9,text='Hello\nworld',words=[]),dict(start=1,end=1.9,text='Γεια σου',words=[])]
        data=self.client.put('/api/captions/'+pid,json=data).json
        return pid,data

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
        saved=self.client.put('/api/captions/'+pid,json=after).json
        self.assertEqual(saved['cues'],after['cues'])
        restored=self.client.post(f'/api/captions/{pid}/restore-karaoke',json={'revision':saved['revision']}).json
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
                busy=self.client.get('/api/captions/'+pid).json
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
        data=self.client.put('/api/captions/'+pid,json=data).json
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
            self.assertEqual(response.status_code,202,response.json)
            pid=response.json['id'];data=self.wait(pid)
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
        pid=response.json['id'];data=self.wait(pid)
        data['cues']=[dict(start=0,end=1,text='Keep me',words=[])]
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

    def test_multilingual_karaoke_and_overrides(self):
        pid,data=self.karaoke_project()
        data['cues']=[dict(start=.1,end=.9,text='Bonjour mon amour',words=[]),dict(start=1,end=1.9,text='사랑해 hello',words=[])]
        data=self.client.put('/api/captions/'+pid,json=data).json
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
        duplicate=self.client.post(f'/api/captions/{pid}/duplicate',json=dict(revision=after['revision'])).json
        self.assertNotEqual(duplicate['id'],pid)
        self.assertEqual(duplicate['cues'],after['cues'])
        self.assertTrue((folder.parent/duplicate['id']/duplicate['preview']).is_file())
        restored=self.client.post(f'/api/captions/{pid}/restore-composition',json=dict(revision=after['revision'])).json
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
        loaded=self.client.get('/api/captions/'+pid).json
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
        def delayed(*args):
            entered.set();release.wait(5);job_process.check_cancelled();return render_args(*args)
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

    def wait(self,pid,state='ready'):
        for _ in range(200):
            data=self.client.get('/api/captions/'+pid).json
            if data['state']!='busy':
                self.assertEqual(data['state'],state,data['status'])
                return data
            time.sleep(.05)
        self.fail('Caption job timed out')

    def test_upload_save_conflict_transcribe_export_and_original_preserved(self):
        original=self.source.read_bytes()
        response=self.client.post('/api/captions',data={'video':(io.BytesIO(original),'sample.mp4')})
        self.assertEqual(response.status_code,202,response.json)
        pid=response.json['id'];data=self.wait(pid)
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
        pid=response.json['id'];data=self.wait(pid)
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
        pid=response.json['id'];data=self.wait(pid)
        data.update(state='busy',cues=[dict(start=0,end=1,text='Saved before restart',words=[])])
        location=self.root/'library'/'Caption Projects'/pid/'project.json'
        location.write_text(json.dumps(data),encoding='utf-8')
        restarted=Flask('restarted')
        register_captions(restarted,self.root/'library',lambda:None,lambda:None,lambda:None,lambda:self.model,lambda p:False)
        data=restarted.test_client().get('/api/captions/'+pid).json
        self.assertEqual(data['state'],'error')
        self.assertIn('interrupted',data['status'])
        self.assertEqual(data['cues'][0]['text'],'Saved before restart')
