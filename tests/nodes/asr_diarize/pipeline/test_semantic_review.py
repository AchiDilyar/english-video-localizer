import pytest
pytest.importorskip("spacy", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("en_core_web_sm", reason="Install B test dependencies with uv sync --extra b-asr")
pytest.importorskip("faster_whisper", reason="Install B test dependencies with uv sync --extra b-asr")

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import spacy
from nodes.asr_diarize.pipeline.common import BError
from nodes.asr_diarize.pipeline.semantic_review import validate_response,check_semantic_boundaries,refine_ranges,DeepSeekHTTP,review_prompt
from nodes.asr_diarize.pipeline.sentence_rules import sentences_from_words,review_ranges


class SemanticReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.nlp=spacy.load('en_core_web_sm',disable=['ner'])

    def words(self,text):
        return [{'word':w,'start':i*.5,'end':i*.5+.4} for i,w in enumerate(text.split())]

    def test_provider_splits_without_any_periods_and_preserves_exact_words(self):
        text='We assign a number to radius and then we calculate the area using that radius'
        words=self.words(text)
        # Force a candidate through duration to exercise the provider callback.
        for w in words:w['start']*=2;w['end']*=2
        received=[]
        def reviewer(payload):
            received.append(copy.deepcopy(payload));return {'ends':[7,len(words)],'needs_human_review':False}
        rows,review=sentences_from_words(words,self.nlp,reviewer)
        self.assertEqual(len(rows),2)
        self.assertEqual(' '.join(r['en'] for r in rows),text)
        self.assertEqual((rows[0]['start_ms'],rows[0]['end_ms']),(0,6800))
        self.assertEqual(rows[1]['start_ms'],7000)
        self.assertEqual(set(received[0]),{'tokens','target_unit_words','max_unit_words'})
        self.assertNotIn('start',json.dumps(received));self.assertNotIn('end_ms',json.dumps(review))

    def test_missing_duplicate_reordered_and_noninteger_boundaries_rejected(self):
        for ends in [[2],[2,2,3],[3,2],[True,3],[0,3],[4]]:
            with self.subTest(ends=ends),self.assertRaises(BError):
                validate_response({'ends':ends,'needs_human_review':False},['a','b','c'])

    def test_rewritten_text_is_not_an_accepted_schema(self):
        with self.assertRaises(BError):validate_response({'text':'New text','ends':[1],'needs_human_review':False},['original'])

    def test_oversized_response_cannot_be_silently_accepted(self):
        with self.assertRaises(BError):validate_response({'ends':[40],'needs_human_review':False},['a']*40)

    def test_bad_provider_preserves_original_and_marks_failure(self):
        words=self.words('Python lets us calculate many different things without writing the answer by hand every time')
        r=[{'first':0,'last':len(words)-1,'text':' '.join(w['word'] for w in words)}]
        actual,report=refine_ranges(r,words,lambda p:{'ends':[2],'needs_human_review':False},self.nlp,max_words=4)
        self.assertEqual(actual[0]['text'],r[0]['text']);self.assertEqual(report['failed'],1)
        self.assertIn('semantic_review_failed',actual[0]['semantic_issues'])

    def test_no_provider_reports_pending_without_claiming_semantic_success(self):
        words=self.words('We calculate a result using Python and store the result in a variable')
        rows,report=sentences_from_words(words,self.nlp)
        self.assertGreater(report['semantic_review']['pending'],0)
        self.assertIn('semantic_review_pending',rows[0]['review_issues'])

    def test_condition_merge_does_not_cascade_across_rest_of_video(self):
        text=['If it rains.','Alice stays home.','Bob opens a book.','Clara reads a newspaper.']
        words=[];ranges=[]
        for s in text:
            start=len(words);words.extend(self.words(s));ranges.append({'first':start,'last':len(words)-1,'text':s})
        actual,_=review_ranges(ranges,words,self.nlp)
        self.assertEqual(len(actual),3)

    def test_http_requires_opt_in_and_configuration_before_network(self):
        with self.assertRaises(BError):DeepSeekHTTP()
        with patch.dict('os.environ',{},clear=True),self.assertRaises(BError):DeepSeekHTTP(allow_network=True)

    def test_http_budget_is_one_actual_request_and_sends_no_times(self):
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"ends":[3],"needs_human_review":false}'}}],
                                               'usage':{'total_tokens':10}}).encode()
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-only-not-a-real-key','DEEPSEEK_MODEL':'test-model'},clear=True),patch('urllib.request.urlopen',return_value=response) as network:
            client=DeepSeekHTTP(allow_network=True,max_calls=1)
            client({'tokens':['Python','is','useful.']})
            with self.assertRaises(BError):client({'tokens':['Python','is','useful.']})
            self.assertEqual(network.call_count,1)
            sent=json.loads(network.call_args.args[0].data)
            self.assertNotIn('test-only-not-a-real-key',json.dumps(sent))
            self.assertEqual(client.usage,[{'total_tokens':10}])

    def test_alignment_is_still_in_memory_during_semantic_review(self):
        from types import SimpleNamespace
        from nodes.asr_diarize.pipeline.sentence_mode import _recognize_sentence
        from unittest.mock import MagicMock
        tokens='We assign a number to radius and then we calculate the area using that radius'.split()
        aligned=[SimpleNamespace(word=t,start=i,end=i+.8) for i,t in enumerate(tokens)]
        model=MagicMock();model.transcribe.return_value=(iter([SimpleNamespace(words=aligned,text=' '.join(tokens))]),None)
        reviewer=MagicMock();reviewer.model='test-model';reviewer.base_url='https://api.deepseek.com'
        reviewer.calls=1;reviewer.usage=[];reviewer.provider='mock-not-live-deepseek'
        reviewer.return_value={'ends':[7,len(tokens)],'needs_human_review':False}
        state={'job_dir':str(Path(__file__).resolve().parents[4]/'tests/tmp/mock-no-files'),
               'request':{'model_dir':'not-used','semantic_review':{'provider':'deepseek','allow_network':True,'max_calls':1,
                                                                     'model':'test-model','base_url':'https://api.deepseek.com'}},
               'audio_ref':'audio.wav','duration_ms':16000,'source_meta':{}}
        with patch('faster_whisper.WhisperModel',return_value=model),patch('nodes.asr_diarize.pipeline.semantic_review.DeepSeekHTTP',return_value=reviewer),patch('nodes.asr_diarize.pipeline.recognition.require_whisper_model',side_effect=lambda value:value):
            result=_recognize_sentence(state)
        self.assertEqual(model.transcribe.call_count,1);self.assertEqual(reviewer.call_count,1)
        self.assertEqual(len(result['table']['sentences']),2)
        self.assertNotIn('words',result['table']);self.assertNotIn('segments',result['table'])

    def test_live_response_is_structurally_valid_but_unsafe_semantic_split_is_vetoed(self):
        fixture=Path(__file__).resolve().parents[3]/'data/asr_diarize/semantic-boundary.json'
        data=json.loads(fixture.read_text(encoding='utf-8'))
        tokens=data['tokens'];response=data['response']
        validate_response(response,tokens)
        with self.assertRaises(BError):check_semantic_boundaries(response,tokens)
