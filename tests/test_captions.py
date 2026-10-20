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


class CaptionWorkflowTests(unittest.TestCase):
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
