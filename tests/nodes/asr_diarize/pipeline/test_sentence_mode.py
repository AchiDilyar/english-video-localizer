import pytest
pytest.importorskip("spacy", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("en_core_web_sm", reason="Install B test dependencies with uv sync --extra b-asr")

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import spacy
from nodes.asr_diarize.pipeline.common import BError
from nodes.asr_diarize.pipeline.sentence_rules import sentences_from_words,validate_sentence_table
from nodes.asr_diarize.pipeline.video_inputs import youtube_url,english_format,download_input
from nodes.asr_diarize.pipeline.sentence_mode import run_sentences

ROOT=Path(__file__).resolve().parents[4]


class SentenceV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.nlp=spacy.load('en_core_web_sm',disable=['ner'])

    def words(self,text,gap_after=None):
        words=[]
        for i,t in enumerate(text.split()):
            start=i*.4+(5 if gap_after is not None and i>=gap_after else 0)
            words.append({'word':t,'start':start,'end':start+.3})
        return words

    def test_pause_inside_sentence_does_not_split(self):
        words=self.words('Today we explain what computation is.',gap_after=4);original=copy.deepcopy(words)
        rows,review=sentences_from_words(words,self.nlp)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['end_ms'],7300)
        self.assertEqual(words,original);self.assertFalse(review['original_asr_timestamps_persisted'])

    def test_two_complete_sentences_are_not_joined(self):
        rows,_=sentences_from_words(self.words('Python is useful. We use it daily.'),self.nlp)
        self.assertEqual(len(rows),2)

    def test_semantic_continuation_repair(self):
        rows,review=sentences_from_words(self.words("We discuss mathematical operations. You can do with Python."),self.nlp)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['en'],'We discuss mathematical operations you can do with Python.')
        self.assertTrue(review['automatic_repairs'])

    def test_dependent_clause_is_joined_to_main_clause(self):
        rows,_=sentences_from_words(self.words('If it rains. Alice stays home.'),self.nlp)
        self.assertEqual(len(rows),1);self.assertIn('Alice',rows[0]['en'])

    def test_questions_stay_separate(self):
        rows,_=sentences_from_words(self.words('What is Python? Who teaches it?'),self.nlp)
        self.assertEqual(len(rows),2);self.assertFalse(rows[1]['review_issues'])

    def test_fragment_flagged_without_inventing_missing_words(self):
        rows,_=sentences_from_words(self.words('First name Anna, last name Bell.'),self.nlp)
        self.assertEqual(rows[0]['review_status'],'needs_human_review')
        self.assertEqual(rows[0]['en'],'First name Anna, last name Bell.')

    def test_abbreviation_does_not_create_a_separate_sentence(self):
        rows,_=sentences_from_words(self.words('Dr. Bell teaches Python.'),self.nlp)
        self.assertEqual(len(rows),1)

    def test_no_native_alignment_in_result_schema(self):
        rows,review=sentences_from_words(self.words('Python is useful.'),self.nlp)
        table={'schema_version':'b-sentences-2','duration_ms':3000,'sentences':rows,'review':review}
        self.assertEqual(validate_sentence_table(table),[])
        self.assertTrue(all(set(row)=={'sentence_id','start_ms','end_ms','en','speaker_id','review_status','review_issues'} for row in rows))
        table['words']=[];self.assertIn('Original ASR structures must not be exported',validate_sentence_table(table))

    def test_zero_duration_utterance_is_not_given_an_invented_timestamp(self):
        words=self.words('Python is useful. Okay?')
        words[-1]['end']=words[-1]['start']
        rows,review=sentences_from_words(words,self.nlp)
        self.assertEqual(len(rows),1)
        self.assertEqual(review['untimed_utterances'][0]['en'],'Okay?')
        self.assertNotIn('start_ms',review['untimed_utterances'][0])

    def test_two_hour_request_is_accepted_and_longer_rejected(self):
        base=(ROOT/'tests/tmp/asr_diarize').resolve();base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as d,patch('nodes.asr_diarize.pipeline.sentence_mode.fingerprint',return_value={'test':'not-real-inference'}),patch('nodes.asr_diarize.pipeline.sentence_mode._execute',return_value={'accepted':True}) as execute:
            # This checks request validation, not decoding; no downloaded sample is needed.
            video=Path(d)/'request-only.mp4'
            video.write_bytes(b'not decoded: execution is mocked')
            run_sentences(str(video),job_dir=Path(d)/'accepted',max_duration_sec=7200)
            self.assertEqual(execute.call_args.args[1]['request']['max_duration_sec'],7200)
            self.assertFalse(execute.call_args.args[1]['request']['external_audio_chunks'])
            with self.assertRaises(BError):run_sentences(str(video),job_dir=Path(d)/'rejected',max_duration_sec=7201)


class YouTubeV2(unittest.TestCase):
    def test_normalize_single_video_not_playlist(self):
        self.assertEqual(youtube_url('https://youtu.be/nykOeWgQcHM?list=abc'),'https://www.youtube.com/watch?v=nykOeWgQcHM')
        with self.assertRaises(BError):youtube_url('https://evil.example/watch?v=nykOeWgQcHM')
        with self.assertRaises(BError):youtube_url('https://www.youtube.com/playlist?list=abc')

    def test_prefer_english_over_automatic_dub(self):
        base={'vcodec':'h264','acodec':'aac','height':360,'ext':'mp4'}
        formats=[{**base,'format_id':'ar','language':'ar','tbr':900},
                 {**base,'format_id':'en','language':'en','format_note':'English (original)','tbr':100}]
        chosen=list(english_format({'formats':formats}))
        self.assertEqual(chosen[0]['format_id'],'en')
