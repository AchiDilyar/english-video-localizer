import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from nodes.asr_diarize.pipeline import group_sample_sentences as m


class GroupContract(unittest.TestCase):
    def setUp(self):
        self.raw={'segments':[{'id':1,'start':1.25,'end':2.1,'text':'What is','words':[{'word':'What','start':1.25,'end':1.5,'probability':.9},{'word':'is','start':1.6,'end':2.1,'probability':.8}]},{'id':2,'start':2.2,'end':3.0,'text':'computation?','words':[{'word':'computation?','start':2.2,'end':3.0,'probability':.95}]}]}
        self.data=json.dumps(self.raw).encode()
        self.plan={'source_asr_sha256':hashlib.sha256(self.data).hexdigest(),'speaker_id':'SPEAKER_00','speaker_method':'single_speaker_assumption','groups':[{'source_segment_ids':[1,2],'reason':'unfinished sentence'}]}

    def test_preserves_words_times_and_original_input(self):
        before=copy.deepcopy(self.raw);b=m.group_bundle(self.raw,self.plan,self.data)
        self.assertEqual(self.raw,before);self.assertEqual(b['original_segments'],before['segments'])
        self.assertEqual([w['word_data'] for w in b['sentence_groups'][0]['words']],[w for s in before['segments'] for w in s['words']])
        self.assertEqual(b['sentence_groups'][0]['start_sec'],1.25);self.assertEqual(b['sentence_groups'][0]['end_sec'],3.0)

    def test_rejects_duplicate_or_missing_or_reordered_sources(self):
        for ids in [[1,1,2],[1],[2,1]]:
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                p=copy.deepcopy(self.plan);p['groups'][0]['source_segment_ids']=ids;m.group_bundle(self.raw,p,self.data)

    def test_rejects_word_rewrite(self):
        self.plan['groups'][0]['reading_text']='What is Python?'
        with self.assertRaises(ValueError):m.group_bundle(self.raw,self.plan,self.data)

    def test_allows_punctuation_and_case_only(self):
        self.plan['groups'][0]['reading_text']='what is computation.'
        self.assertEqual(m.group_bundle(self.raw,self.plan,self.data)['sentence_groups'][0]['reading_edit'],'punctuation_or_case_only')

    def test_rejects_plan_for_different_recording(self):
        with self.assertRaises(ValueError):m.group_bundle(self.raw,self.plan,b'other recording')
