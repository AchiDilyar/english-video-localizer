import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodes.asr_diarize.pipeline.common import BError, object_hash, write_json
from nodes.asr_diarize.pipeline.sources import select_source
from nodes.asr_diarize.pipeline.grouping import make_groups
from nodes.asr_diarize.pipeline.exporting import build_timetable, validate_timetable
import nodes.asr_diarize.pipeline.workflow as workflow

ROOT=Path(__file__).resolve().parents[4]


class Contracts(unittest.TestCase):
    def test_registered_id_and_media_url_selection(self):
        registry=ROOT/'tests/data/asr_diarize/b_sources.example.json'
        s=select_source('mit-python-remote-45s',registry)
        self.assertEqual(select_source(s['media_url'],registry)['source_id'],s['source_id'])
        self.assertEqual(select_source('mit-python-local-45s',registry)['kind'],'local')

    def test_unregistered_url_is_not_downloaded(self):
        with self.assertRaises(BError) as c:select_source('https://example.com/unregistered.mp4',ROOT/'tests/data/asr_diarize/b_sources.example.json')
        self.assertEqual(c.exception.code,'SOURCE_NOT_REGISTERED')

    def test_registry_permission_and_range(self):
        parent=ROOT/'tests/tmp/asr_diarize';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as d:
            spec={'source_id':'a','kind':'https_excerpt','page_url':'https://example.com/page',
                  'media_url':'https://example.com/clip.mp4','license':'CC BY','license_url':'https://example.com/license',
                  'attribution':'Test author','authorization_status':'pending','excerpt_start_sec':1,
                  'excerpt_duration_sec':2,'original_offset_ms':1000}
            p=Path(d)/'registry.json'
            write_json(p,{'schema_version':'b-sources-1','sources':[spec]})
            with self.assertRaises(BError) as c:select_source('a',p)
            self.assertEqual(c.exception.code,'SOURCE_UNAUTHORIZED')
            spec['authorization_status']='confirmed';spec['excerpt_duration_sec']=float('inf')
            # JSON standards forbid infinity: test invalid registered range directly via negative length.
            spec['excerpt_duration_sec']=-1;write_json(p,{'schema_version':'b-sources-1','sources':[spec]})
            with self.assertRaises(BError):select_source('a',p)

    def sample(self):
        return {'segments':[{'id':1,'start':1.,'end':2.,'text':'What is','words':[{'word':'What','start':1.,'end':1.3,'probability':.9},{'word':'is','start':1.4,'end':2.,'probability':.9}]},
                            {'id':2,'start':2.,'end':2.5,'text':'computation?','words':[{'word':'computation?','start':2.,'end':2.5,'probability':.9}]}]}

    def test_general_grouping_preserves_raw_and_word_trace(self):
        raw=self.sample();before=copy.deepcopy(raw)
        import hashlib
        source=json.dumps(raw).encode()
        grouped=make_groups(raw,source,'audio',hashlib.sha256(source).hexdigest(),'single_assumed')
        bundle=build_timetable(raw,grouped,{'original_offset_ms':60000},{'duration_ms':3000,'source_sha256':'x'},{'speaker_mode':'single_assumed'})
        self.assertEqual(raw,before);self.assertEqual(len(bundle['sentence_groups']),1)
        self.assertEqual(bundle['original_segments'],before['segments'])
        self.assertEqual(validate_timetable(bundle),[])
        altered=copy.deepcopy(bundle);altered['sentence_groups'][0]['source_segment_ids'].pop()
        self.assertIn('Group coverage is missing, duplicated or reordered',validate_timetable(altered))
        altered=copy.deepcopy(bundle);altered['segments'][0]['words'][0]['raw_word']['start']=.7
        self.assertIn('Raw words changed',validate_timetable(altered))

    def test_unknown_speaker_does_not_auto_merge(self):
        import hashlib
        raw=self.sample();source=json.dumps(raw).encode()
        grouped=make_groups(raw,source,'audio',hashlib.sha256(source).hexdigest(),'unknown')
        self.assertEqual(len(grouped['sentence_groups']),2)
        self.assertIsNone(grouped['sentence_groups'][0]['speaker_id'])

    def test_word_envelope_adjustment_is_explicit_and_preserves_original(self):
        import hashlib
        raw=self.sample();raw['segments'][0]['start']=1.2
        original=copy.deepcopy(raw);source=json.dumps(raw).encode()
        grouped=make_groups(raw,source,'audio',hashlib.sha256(source).hexdigest(),'single_assumed')
        b=build_timetable(raw,grouped,{'original_offset_ms':0},{'duration_ms':3000,'source_sha256':'x'},{'speaker_mode':'single_assumed'})
        self.assertEqual(raw,original);self.assertEqual(b['original_segments'],original['segments'])
        self.assertEqual(b['segments'][0]['start_ms'],1000)
        self.assertEqual(b['segments'][0]['timing_adjustment']['raw_start_ms'],1200)
        self.assertEqual(b['segments'][0]['timing_adjustment']['start_delta_ms'],-200)
        self.assertEqual(b['sentence_groups'][0]['start_ms'],1000)
        self.assertEqual(validate_timetable(b),[])
        b['segments'][0]['timing_adjustment']=None
        self.assertIn('Unexplained normalized segment time adjustment',validate_timetable(b))

    def test_real_langgraph_invalid_route_blocks_export(self):
        parent=ROOT/'tests/tmp/asr_diarize';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as d:
            passthrough=lambda state: ({},[])
            bad=lambda state: ({'validation_errors':['intentional invalid test record']},[])
            with patch.object(workflow,'resolve_node',passthrough),patch.object(workflow,'acquire_node',passthrough),patch.object(workflow,'audio_node',passthrough),patch.object(workflow,'asr_node',passthrough),patch.object(workflow,'grouping_node',passthrough),patch.object(workflow,'validate_node',bad),patch.object(workflow,'export_node',side_effect=AssertionError('Invalid result must not export')):
                state=workflow.build_b_graph().invoke({'job_dir':d,'request':{}})
            self.assertEqual(state['status'],'blocked_validation')
            self.assertTrue((Path(d)/'review-required.json').is_file())
            self.assertFalse((Path(d)/'timetable.json').exists())
