import pytest
pytest.importorskip("numpy", reason="Install B test dependencies with uv sync --extra b-asr")

import copy
import unittest
from nodes.asr_diarize.pipeline.diarization import assign_speakers,model_files,diarize
from nodes.asr_diarize.pipeline.sentence_rules import validate_sentence_table
from nodes.asr_diarize.pipeline.common import BError


class SpeakerAttributionTests(unittest.TestCase):
    def table(self,start,end):
        return {'schema_version':'b-sentences-2','duration_ms':8000,'sentences':[{'sentence_id':'s1','start_ms':start,'end_ms':end,
                'speaker_id':None,'en':'Python is useful.','review_issues':[],'review_status':'automatic_checks_passed'}],
                'review':{},'verification':{}}

    def result(self):
        return {'speaker_ids':['speaker_001','speaker_002'],'metadata':{},'turns':[
            {'start_ms':1000,'end_ms':3000,'speaker_id':'speaker_001'},
            {'start_ms':3000,'end_ms':5000,'speaker_id':'speaker_002'},
            {'start_ms':6000,'end_ms':8000,'speaker_id':'speaker_001'}]}

    def test_same_speaker_returns_with_same_label_and_table_is_not_mutated(self):
        table=self.table(6000,8000);before=copy.deepcopy(table);out=assign_speakers(table,self.result())
        self.assertEqual(table,before);self.assertEqual(out['sentences'][0]['speaker_id'],'speaker_001')
        self.assertTrue(out['verification']['automatic_diarization_executed'])
        self.assertFalse(out['verification']['speaker_labels_human_verified'])

    def test_second_voice_gets_second_label(self):
        out=assign_speakers(self.table(3100,4900),self.result());self.assertEqual(out['sentences'][0]['speaker_id'],'speaker_002')

    def test_mixed_speakers_are_not_forced_into_one_identity(self):
        out=assign_speakers(self.table(2000,4000),self.result())
        self.assertIsNone(out['sentences'][0]['speaker_id'])
        self.assertIn('speaker_duration_tie',out['sentences'][0]['review_issues'])

    def test_no_speech_stays_unknown(self):
        out=assign_speakers(self.table(0,500),self.result());self.assertIsNone(out['sentences'][0]['speaker_id'])

    def test_simultaneous_speech_stays_unknown(self):
        result=self.result();result['turns'][1].update(start_ms=1000,end_ms=3000)
        out=assign_speakers(self.table(1000,3000),result);self.assertIsNone(out['sentences'][0]['speaker_id'])

    def test_duplicate_turns_do_not_double_count_speaker_coverage(self):
        result=self.result();result['turns'].append(dict(result['turns'][0]))
        out=assign_speakers(self.table(1000,3000),result)
        self.assertEqual(out['sentences'][0]['speaker_assignment']['top_sentence_time_coverage'],1)

    def test_diarization_does_not_modify_sentence_text_or_final_times(self):
        table=self.table(1000,3000);out=assign_speakers(table,self.result())
        for name in ['sentence_id','en','start_ms','end_ms']:self.assertEqual(table['sentences'][0][name],out['sentences'][0][name])

    def test_invalid_speaker_and_turn_are_rejected(self):
        out=assign_speakers(self.table(1000,3000),self.result());self.assertEqual(validate_sentence_table(out),[])
        out['sentences'][0]['speaker_id']='unregistered';self.assertIn('Unknown speaker ID',validate_sentence_table(out))
        out['diarization']['turns'][0]['end_ms']=9999;self.assertIn('Invalid speaker turn',validate_sentence_table(out))

    def test_missing_model_is_an_explicit_error(self):
        with self.assertRaises(BError):model_files('models/nonexistent-diarization-model')

    def test_short_edge_overlap_uses_dominant_speaker(self):
        r=self.result();r['turns']=[{'start_ms':0,'end_ms':8000,'speaker_id':'speaker_001'},
                                  {'start_ms':0,'end_ms':600,'speaker_id':'speaker_002'}]
        out=assign_speakers(self.table(0,8000),r)
        self.assertEqual(out['sentences'][0]['speaker_id'],'speaker_001')
        self.assertEqual(out['sentences'][0]['speaker_assignment']['decision'],'majority_speaker')
        self.assertNotIn('speaker_boundary_overlap',out['sentences'][0]['review_issues'])

    def test_same_overlap_in_middle_uses_majority(self):
        r=self.result();r['turns']=[{'start_ms':0,'end_ms':8000,'speaker_id':'speaker_001'},
                                  {'start_ms':3500,'end_ms':4100,'speaker_id':'speaker_002'}]
        self.assertEqual(assign_speakers(self.table(0,8000),r)['sentences'][0]['speaker_id'],'speaker_001')

    def test_sequential_speaker_switch_still_uses_whole_sentence_majority(self):
        r=self.result();r['turns']=[{'start_ms':0,'end_ms':6800,'speaker_id':'speaker_001'},
                                  {'start_ms':6800,'end_ms':8000,'speaker_id':'speaker_002'}]
        self.assertEqual(assign_speakers(self.table(0,8000),r)['sentences'][0]['speaker_id'],'speaker_001')

    def test_short_sentence_also_uses_majority(self):
        r=self.result();r['turns']=[{'start_ms':0,'end_ms':2000,'speaker_id':'speaker_001'},
                                  {'start_ms':0,'end_ms':500,'speaker_id':'speaker_002'}]
        self.assertEqual(assign_speakers(self.table(0,2000),r)['sentences'][0]['speaker_id'],'speaker_001')

    def test_more_than_half_assigns_but_exact_half_does_not(self):
        r=self.result();r['turns']=[{'start_ms':0,'end_ms':4001,'speaker_id':'speaker_001'},
                                  {'start_ms':4001,'end_ms':8000,'speaker_id':'speaker_002'}]
        self.assertEqual(assign_speakers(self.table(0,8000),r)['sentences'][0]['speaker_id'],'speaker_001')
        r['turns'][0]['end_ms']=4000;r['turns'][1]['start_ms']=4000
        self.assertIsNone(assign_speakers(self.table(0,8000),r)['sentences'][0]['speaker_id'])

    def test_plurality_without_majority_stays_unknown(self):
        r=self.result();r['speaker_ids'].append('speaker_003')
        r['turns']=[{'start_ms':0,'end_ms':3200,'speaker_id':'speaker_001'},
                    {'start_ms':3200,'end_ms':6000,'speaker_id':'speaker_002'},
                    {'start_ms':6000,'end_ms':8000,'speaker_id':'speaker_003'}]
        self.assertEqual(assign_speakers(self.table(0,8000),r)['sentences'][0]['speaker_assignment']['decision'],'no_majority')

    def test_old_boundary_warning_is_removed_after_majority_assignment(self):
        table=self.table(1000,3000);table['sentences'][0]['review_issues']=['speaker_boundary_overlap']
        table['sentences'][0]['review_status']='needs_human_review'
        row=assign_speakers(table,self.result())['sentences'][0]
        self.assertEqual(row['review_issues'],[])
        self.assertEqual(row['review_status'],'automatic_checks_passed')
