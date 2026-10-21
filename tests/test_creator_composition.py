import copy
from pathlib import Path
import tempfile
import unittest
import creator_composition as comp

class CompositionDataTests(unittest.TestCase):
    def test_trim_shifts_words_and_flags_cut_lines_without_mutating_original(self):
        cues=[dict(start=.2,end=1,text='Bonjour hello',words=[dict(text='Bonjour',start=.2,end=.6),dict(text='hello',start=.6,end=1)]),
              dict(start=2,end=3,text='안녕',words=[])]
        original=copy.deepcopy(cues)
        shifted=comp.shift_cues(cues,.5,3)
        self.assertEqual(shifted[0]['start'],.7)
        self.assertEqual(shifted[0]['words'][0]['end'],1.1)
        self.assertEqual(shifted[1]['end'],3)
        self.assertEqual(shifted[1]['karaoke']['state'],'review')
        self.assertEqual(comp.shift_cues(cues,-1.5,2)[0]['text'],'안녕')
        self.assertEqual(cues,original)

    def test_validation_rejects_nonfinite_reversed_ranges_and_filter_injection(self):
        base={**comp.DEFAULTS,'end':5}
        for change in [dict(start=6),dict(end=0),dict(offset=float('nan')),dict(color='red;movie=secret'),dict(fit='invalid'),dict(loop='yes'),dict(fade_out=6),dict(zoom=1)]:
            with self.subTest(change=change), self.assertRaises(ValueError): comp.validate({**base,**change},5)
        self.assertEqual(comp.validate(base,5)['end'],5)

    def test_asset_paths_and_future_schema_are_rejected(self):
        folder=Path.cwd()
        for name in ('../secret','a/b','a\\b','C:\\secret'):
            with self.assertRaises(ValueError):comp.local_asset(folder,dict(file=name))
        with self.assertRaises(ValueError):comp.migrate(dict(studio=dict(version=999)),folder)

    def test_legacy_migration_and_track_offsets_are_nondestructive(self):
        artifacts=Path(__file__).resolve().parents[1]/'audit_artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as directory:
            folder=Path(directory);(folder/'song.wav').touch();(folder/'background.png').touch()
            old=dict(duration=10,width=1080,height=1920,source='original.mp4',style={'font':'Arial'},composition={'shape':'portrait','color':'#123456','visualizer':True})
            before=copy.deepcopy(old);studio=comp.migrate(old,folder)
            self.assertEqual(old,before)
            self.assertEqual(studio['assets']['audio']['file'],'song.wav')
            self.assertEqual(studio['assets']['background']['kind'],'image')
            self.assertEqual(studio['tracks'][1]['clips'][0]['source_offset'],0)
            self.assertEqual(studio['timebase'],'seconds')
