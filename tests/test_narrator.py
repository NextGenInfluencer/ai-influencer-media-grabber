"""Unit and integration tests for Studio AI Narrator & Voiceover (narrator.py + captions.py routes)."""
import tests._isolation  # Must precede application imports
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

import numpy as np

import app_local
import narrator


def _make_sine_wav_bytes(duration_sec: float = 0.6, freq: float = 440.0, sample_rate: int = 24000) -> bytes:
    t = np.linspace(0.0, duration_sec, int(sample_rate * duration_sec), endpoint=False, dtype=np.float32)
    samples = 0.35 * np.sin(2.0 * np.pi * freq * t)
    pcm16 = (samples * 32767.0).astype('<i2')
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


class NarratorEngineUnitTests(unittest.TestCase):
    def test_sec_ms_gec_v2_vector(self):
        token = narrator.generate_sec_ms_gec_v2(1700000000)
        self.assertEqual(
            token,
            '2CD23A2CA0B2595A-F3C846C370E05F9CC83ACC5F995C5F5D87A4D0F14CE8936A0F902E64099E38A2',
        )

    def test_format_edge_voice_and_ssml_escaping(self):
        full = narrator.format_edge_voice_name('el-GR-AthinaNeural')
        self.assertEqual(full, 'Microsoft Server Speech Text to Speech Voice (el-GR, AthinaNeural)')
        ssml = narrator.build_edge_ssml('Rock & Roll <Live>', 'en-US-AvaMultilingualNeural', rate_pct=10, pitch_hz=-4)
        self.assertIn("pitch='-4Hz' rate='+10%'", ssml)
        self.assertIn('Rock &amp; Roll &lt;Live&gt;', ssml)

    def test_kokoro_phoneme_to_word_mapping(self):
        spoken = [
            {'phoneme': 'h', 'start': 0.05, 'end': 0.15},
            {'phoneme': 'ə', 'start': 0.15, 'end': 0.35},
            {'phoneme': ' ', 'start': 0.35, 'end': 0.40},
            {'phoneme': 'w', 'start': 0.40, 'end': 0.60},
            {'phoneme': 'ɜːld', 'start': 0.60, 'end': 0.90},
        ]
        words = narrator.map_kokoro_phoneme_timings_to_words('Hello world!', spoken, 1.0)
        self.assertEqual([w['text'] for w in words], ['Hello', 'world!'])
        self.assertEqual(words[0]['start'], 0.05)
        self.assertEqual(words[0]['end'], 0.35)
        self.assertEqual(words[1]['start'], 0.40)
        self.assertEqual(words[1]['end'], 0.90)

        # Fallback when phoneme groups don't match word count
        fallback = narrator.map_kokoro_phoneme_timings_to_words('Testing 2026 now', [], 1.5)
        self.assertEqual([w['text'] for w in fallback], ['Testing', '2026', 'now'])
        self.assertAlmostEqual(fallback[-1]['end'], 1.5, places=2)

    def test_elevenlabs_character_alignment_to_words(self):
        alignment = {
            'characters': list('Hi there'),
            'character_start_times_seconds': [0.0, 0.1, 0.2, 0.25, 0.35, 0.45, 0.55, 0.65],
            'character_end_times_seconds': [0.1, 0.2, 0.25, 0.35, 0.45, 0.55, 0.65, 0.80],
        }
        words = narrator.map_elevenlabs_alignment_to_words(alignment, 'Hi there')
        self.assertEqual(words, [
            {'start': 0.0, 'end': 0.2, 'text': 'Hi'},
            {'start': 0.25, 'end': 0.8, 'text': 'there'},
        ])

    def test_master_line_audio_and_sidechain_mix(self):
        raw_wav = _make_sine_wav_bytes(0.75)
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            line1 = tdir / 'narr_line_1.wav'
            line2 = tdir / 'narr_line_2.wav'
            dur1 = narrator.master_line_audio(raw_wav, '.wav', line1, tone='warm_podcast', atempo=1.0, cwd=tdir)
            dur2 = narrator.master_line_audio(raw_wav, '.wav', line2, tone='deep_cinema', atempo=1.15, cwd=tdir)
            self.assertGreater(dur1, 0.4)
            self.assertLess(dur2, dur1)

            bus = tdir / 'bus.wav'
            narrator.build_voice_bus_wav([(0.1, line1), (1.0, line2)], 2.2, bus, narrator_volume=1.1)
            self.assertTrue(bus.is_file())

            master = tdir / 'master.wav'
            narrator.mix_voice_with_background(
                bus,
                line1,
                2.2,
                master,
                background_volume=0.3,
                ducking=True,
                cwd=tdir,
            )
            self.assertTrue(master.is_file())
            with wave.open(str(master), 'rb') as wf:
                self.assertEqual(wf.getnchannels(), 2)
                self.assertEqual(wf.getframerate(), 44100)


class NarratorRoutesIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app_local.app.test_client()
        cls.client.get('/')
        with cls.client.session_transaction() as session:
            cls.headers = {'X-Media-Token': session['api_token']}

    def _wait_ready(self, pid: str, timeout: float = 20.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            res = self.client.get(f'/api/captions/{pid}', headers=self.headers)
            self.assertEqual(res.status_code, 200)
            data = res.json
            if data['state'] != 'busy':
                self.assertEqual(data['state'], 'ready', data.get('status'))
                return data
            time.sleep(0.05)
        self.fail(f'Project {pid} stayed busy for >{timeout}s')

    def _create_song_project(self) -> dict:
        song_bytes = _make_sine_wav_bytes(duration_sec=3.0, freq=220.0)
        res = self.client.post(
            '/api/captions',
            data={
                'audio': (io.BytesIO(song_bytes), 'test_song.wav'),
                'shape': 'portrait',
                'color': '#141526',
            },
            headers={'X-Media-Token': self.headers['X-Media-Token']},
            content_type='multipart/form-data',
        )
        self.assertIn(res.status_code, (201, 202), res.get_data(as_text=True))
        return self._wait_ready(res.json['id'])

    def test_voices_settings_and_preview_endpoints(self):
        res = self.client.get('/api/captions/narrator/voices?language=el', headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(any(v['id'] == 'el-GR-AthinaNeural' for v in res.json['voices']['edge']))

        # Save and clear ElevenLabs API key
        with patch.object(narrator, 'list_elevenlabs_voices', return_value=[{'id': 'v123456', 'name': 'Rachel', 'lang': 'multi', 'gender': 'Female', 'accent': 'US', 'tag': 'Narration'}]):
            s_res = self.client.post('/api/captions/narrator/settings', json={'elevenlabs_key': 'sk_test_1234567890'}, headers=self.headers)
            self.assertEqual(s_res.status_code, 200)
            self.assertTrue(s_res.json['elevenlabs_configured'])
            self.assertEqual(s_res.json['voices']['elevenlabs'][0]['name'], 'Rachel')

            c_res = self.client.post('/api/captions/narrator/settings', json={'elevenlabs_key': ''}, headers=self.headers)
            self.assertEqual(c_res.status_code, 200)

        # Preview endpoint with mocked synthesis
        fake_wav = _make_sine_wav_bytes(0.4)
        with patch.object(narrator, 'synthesize_line_raw', return_value=(fake_wav, '.wav', [])):
            p_res = self.client.post(
                '/api/captions/narrator/preview',
                json={'settings': {'engine': 'edge', 'voice': 'en-US-AvaMultilingualNeural', 'tone': 'warm_podcast'}, 'language': 'en'},
                headers=self.headers,
            )
            self.assertEqual(p_res.status_code, 200)
            self.assertEqual(p_res.mimetype, 'audio/wav')
            self.assertGreater(len(p_res.data), 1000)

    def test_full_narration_per_line_regeneration_and_rollback(self):
        proj = self._create_song_project()
        pid = proj['id']
        orig_source = proj['source']

        # Save 2 initial cues
        cues = [
            {'id': 'cue_line_001', 'start': 0.1, 'end': 1.2, 'text': 'First studio line', 'words': []},
            {'id': 'cue_line_002', 'start': 1.4, 'end': 2.6, 'text': 'Second studio line', 'words': []},
        ]
        save_res = self.client.put(
            f'/api/captions/{pid}',
            json={'revision': proj['revision'], 'cues': cues, 'style': proj['style']},
            headers=self.headers,
        )
        self.assertEqual(save_res.status_code, 200)
        proj = save_res.json

        fake_wav = _make_sine_wav_bytes(0.55)
        fake_words_1 = [{'start': 0.0, 'end': 0.18, 'text': 'First'}, {'start': 0.18, 'end': 0.36, 'text': 'studio'}, {'start': 0.36, 'end': 0.55, 'text': 'line'}]
        with patch.object(narrator, 'synthesize_line_raw', return_value=(fake_wav, '.wav', fake_words_1)) as mock_synth:
            n_res = self.client.post(
                f'/api/captions/{pid}/narrate',
                json={
                    'revision': proj['revision'],
                    'settings': {
                        'engine': 'edge',
                        'voice': 'en-US-AvaMultilingualNeural',
                        'tone': 'warm_podcast',
                        'timing_mode': 'sync_captions',
                        'track': 'original',
                        'ducking': True,
                        'background_volume': 0.25,
                    },
                },
                headers=self.headers,
            )
            self.assertIn(n_res.status_code, (200, 202))
            narrated = self._wait_ready(pid)
            self.assertEqual(mock_synth.call_count, 2)

        self.assertNotEqual(narrated['source'], orig_source)
        self.assertEqual(narrated['narrator']['tone'], 'warm_podcast')
        self.assertIn('narration_backup', narrated)
        self.assertEqual(len(narrated['cues'][0]['words']), 3)

        # Stream individual line audio
        audio_res = self.client.get(f'/api/captions/{pid}/narrate-line/cue_line_001/audio', headers=self.headers)
        self.assertEqual(audio_res.status_code, 200)
        self.assertEqual(audio_res.mimetype, 'audio/wav')
        audio_res.close()

        # Regenerate ONLY line 2 with edited text (confirm only 1 TTS call is made and vocal tone stays locked)
        fake_words_2 = [{'start': 0.0, 'end': 0.2, 'text': 'Updated'}, {'start': 0.2, 'end': 0.4, 'text': 'second'}, {'start': 0.4, 'end': 0.55, 'text': 'line'}]
        with patch.object(narrator, 'synthesize_line_raw', return_value=(fake_wav, '.wav', fake_words_2)) as mock_line_synth:
            l_res = self.client.post(
                f'/api/captions/{pid}/narrate-line',
                json={
                    'revision': narrated['revision'],
                    'cue_id': 'cue_line_002',
                    'text': 'Updated second line',
                },
                headers=self.headers,
            )
            self.assertIn(l_res.status_code, (200, 202))
            updated = self._wait_ready(pid)
            self.assertEqual(mock_line_synth.call_count, 1)
            # Verify previous_text context was passed
            self.assertEqual(mock_line_synth.call_args.kwargs['previous_text'], 'First studio line')

        self.assertEqual(updated['cues'][1]['text'], 'Updated second line')
        self.assertEqual([w['text'] for w in updated['cues'][1]['words']], ['Updated', 'second', 'line'])
        self.assertEqual(updated['narrator']['tone'], 'warm_podcast')

        # 1-Click Rollback via /restore-narration
        r_res = self.client.post(
            f'/api/captions/{pid}/restore-narration',
            json={'revision': updated['revision']},
            headers=self.headers,
        )
        self.assertEqual(r_res.status_code, 200)
        restored = r_res.json
        self.assertEqual(restored['source'], orig_source)
        self.assertNotIn('narration_backup', restored)
        self.assertEqual(restored['cues'][1]['text'], 'Second studio line')

    def test_script_and_translation_dubbing_and_fit_mode(self):
        proj = self._create_song_project()
        pid = proj['id']
        fake_wav = _make_sine_wav_bytes(0.8)
        with patch.object(narrator, 'synthesize_line_raw', return_value=(fake_wav, '.wav', [])):
            # 1. Script narration creates cues + voiceover together
            s_res = self.client.post(
                f'/api/captions/{pid}/narrate',
                json={
                    'revision': proj['revision'],
                    'script': 'Welcome to the studio\nHere is line two',
                    'settings': {
                        'engine': 'edge',
                        'voice': 'en-US-AndrewMultilingualNeural',
                        'tone': 'crisp_creator',
                        'track': 'script',
                        'timing_mode': 'sync_captions',
                    },
                },
                headers=self.headers,
            )
            self.assertIn(s_res.status_code, (200, 202))
            proj = self._wait_ready(pid)
            self.assertEqual(len(proj['cues']), 2)
            self.assertEqual(proj['cues'][0]['text'], 'Welcome to the studio')
            self.assertEqual(proj['cues'][1]['text'], 'Here is line two')

            # 2. Fit captions mode with translation dubbing
            from assets import lyric_tracks
            cues_with_tr = proj['cues']
            for idx, c in enumerate(cues_with_tr):
                c['translations'] = {'el': lyric_tracks.make_translation(f'Ελληνική γραμμή {idx + 1}', c['text'])}
            style = {**proj['style'], 'translation_language': 'el'}
            put_res = self.client.put(
                f'/api/captions/{pid}',
                json={'revision': proj['revision'], 'cues': cues_with_tr, 'style': style},
                headers=self.headers,
            )
            self.assertEqual(put_res.status_code, 200)
            proj = put_res.json

            f_res = self.client.post(
                f'/api/captions/{pid}/narrate',
                json={
                    'revision': proj['revision'],
                    'settings': {
                        'engine': 'edge',
                        'voice': 'el-GR-AthinaNeural',
                        'tone': 'deep_cinema',
                        'track': 'translation',
                        'timing_mode': 'fit_captions',
                    },
                },
                headers=self.headers,
            )
            self.assertIn(f_res.status_code, (200, 202))
            dubbed = self._wait_ready(pid)
            self.assertEqual(dubbed['narrator']['track'], 'translation')
            self.assertEqual(dubbed['narrator']['timing_mode'], 'fit_captions')


if __name__ == '__main__':
    unittest.main()
