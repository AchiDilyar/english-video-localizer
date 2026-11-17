from types import SimpleNamespace
import unittest
from nodes.asr_diarize.community1_worker import canonical_turns


class CommunityFormatTests(unittest.TestCase):
    def test_ordering_clipping_and_repeated_speaker_identity(self):
        class Annotation:
            def itertracks(self,yield_label):
                return iter([(SimpleNamespace(start=2,end=3),'x','B'),(SimpleNamespace(start=-.1,end=1),'y','A'),
                             (SimpleNamespace(start=4,end=6),'z','A')])
        turns,ids=canonical_turns(Annotation(),5000)
        self.assertEqual(ids,['speaker_001','speaker_002'])
        self.assertEqual([x['speaker_id'] for x in turns],['speaker_001','speaker_002','speaker_001'])
        self.assertEqual((turns[0]['start_ms'],turns[-1]['end_ms']),(0,5000))

    def test_empty_result_is_not_reported_as_success(self):
        class Annotation:
            def itertracks(self,yield_label):return iter([])
        with self.assertRaises(ValueError):canonical_turns(Annotation(),5000)
