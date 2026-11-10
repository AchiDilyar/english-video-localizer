import pytest
pytest.importorskip("spacy", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("en_core_web_sm", reason="Install B test dependencies with uv sync --extra b-asr")

import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import wave

import spacy
from nodes.asr_diarize.pipeline.audio_recheck import insertion_only,recheck_table


class AudioRecheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.nlp=spacy.load('en_core_web_sm',disable=['ner'])

    def table(self):
        return {'schema_version':'b-sentences-2','duration_ms':10000,
                'sentences':[{'sentence_id':'sentence_000001','start_ms':1000,'end_ms':2400,'en':'We use the',
                'speaker_id':None,'review_status':'needs_human_review','review_issues':['possible_unfinished_sentence']},
                {'sentence_id':'sentence_000002','start_ms':5000,'end_ms':7000,'en':'Python is useful.',
                'speaker_id':None,'review_status':'automatic_checks_passed','review_issues':[]}],
                'review':{'untimed_utterances':[]},'execution':{'transcribe_calls':1}}

    def run_case(self,second=None,start_ms=None):
        table=self.table()
        if start_ms is not None:table['sentences'][0]['start_ms']=start_ms
        before=copy.deepcopy(table)
        class Model:
            calls=0
            def transcribe(self,samples,**kwargs):
                self.calls+=1
                text=second if self.calls==2 and second else 'We use the computer.'
                words=[SimpleNamespace(word=t,start=1+i*.5,end=1.4+i*.5) for i,t in enumerate(text.split())]
                return iter([SimpleNamespace(words=words)]),None
        base=Path(__file__).resolve().parents[4]/'tests/tmp/audio_recheck';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as directory:
            path=Path(directory)/'audio.wav'
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(320000))
            result=recheck_table(table,path,Model(),self.nlp)
        self.assertEqual(table,before)
        return result

    def test_insertion_guard_rejects_deletion_and_replacement(self):
        self.assertTrue(insertion_only('We use the','We use the computer.'))
        self.assertFalse(insertion_only('We use the','We use a computer.'))
        self.assertFalse(insertion_only('We use the computer','We use the'))

    def test_two_decoder_agreement_provisionally_adds_audio_words_with_final_time(self):
        result=self.run_case();row=result['sentences'][0]
        self.assertEqual(row['en'],'We use the computer.')
        self.assertEqual(row['end_ms'],2900)
        self.assertIn('audio_recheck_changed_needs_human_confirmation',row['review_issues'])
        self.assertEqual(result['execution']['transcribe_calls'],3)
        self.assertEqual(result['review']['audio_recheck']['provisional_repairs'],1)
        self.assertNotIn('words',result['review']['audio_recheck']['records'][0])

    def test_disagreement_preserves_original(self):
        result=self.run_case('We use the program.')
        self.assertEqual(result['sentences'][0]['en'],'We use the')
        self.assertEqual(result['review']['audio_recheck']['records'][0]['status'],'manual_review_decoder_disagreement')

    def test_leading_word_in_unassigned_gap_is_recovered_without_guessing_time(self):
        result=self.run_case(start_ms=1300)
        self.assertEqual(result['sentences'][0]['en'],'We use the computer.')
        self.assertEqual(result['sentences'][0]['start_ms'],1000)
