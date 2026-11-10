import pytest
pytest.importorskip("numpy", reason="Install B test dependencies with uv sync --extra b-asr")

from dataclasses import dataclass
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import urllib.error
import wave

import numpy as np
from nodes.asr_diarize.pipeline.common import BError,read_json
from nodes.asr_diarize.pipeline.downloads import download_file
from nodes.asr_diarize.pipeline.chunking import plan_chunks,write_chunk,globalize,transcribe_chunks

ROOT=Path(__file__).resolve().parents[4]


class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None):
        super().__init__(data);self.status=status;self.headers=headers or {}


class TempCase(unittest.TestCase):
    def setUp(self):
        base=(ROOT/'tests/tmp/asr_diarize').resolve();base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)

    def tearDown(self):
        if not self.root.resolve().is_relative_to((ROOT/'tests/tmp/asr_diarize').resolve()):raise RuntimeError('Unsafe cleanup')
        self.temp.cleanup()


class DownloadTests(TempCase):
    def setUp(self):
        super().setUp();self.data=b'abcd'*32768;self.target=self.root/'video.mp4';self.url='https://example.org/video.mp4'

    def first_pause(self):
        with self.assertRaises(BError) as c:
            download_file(self.url,self.target,pause_once_bytes=65536,
                opener=lambda *a,**k:Response(self.data,headers={'Content-Length':str(len(self.data)),'ETag':'"v1"'}))
        self.assertEqual(c.exception.code,'DOWNLOAD_PAUSED')

    def test_verified_range_resume_preserves_bytes(self):
        self.first_pause()
        def resumed(request,**kw):
            self.assertEqual(request.get_header('Range'),'bytes=65536-')
            return Response(self.data[65536:],206,{'Content-Range':f'bytes 65536-{len(self.data)-1}/{len(self.data)}','ETag':'"v1"'})
        record=download_file(self.url,self.target,opener=resumed)
        self.assertEqual(self.target.read_bytes(),self.data)
        self.assertTrue(record['complete']);self.assertEqual(record['attempts'][-1]['requested_offset'],65536)

    def test_server_ignoring_range_restarts_without_appending(self):
        self.first_pause()
        record=download_file(self.url,self.target,opener=lambda *a,**k:Response(self.data,headers={'Content-Length':str(len(self.data)),'ETag':'"v2"'}))
        self.assertEqual(self.target.read_bytes(),self.data)
        self.assertTrue(list(self.root.glob('*.discarded-*')))

    def test_wrong_range_and_changed_validator_are_rejected(self):
        self.first_pause()
        for headers in [{'Content-Range':f'bytes 0-{len(self.data)-1}/{len(self.data)}','ETag':'"v1"'},
                        {'Content-Range':f'bytes 65536-{len(self.data)-1}/{len(self.data)}','ETag':'"v2"'}]:
            with self.subTest(headers=headers),self.assertRaises(BError):
                download_file(self.url,self.target,opener=lambda *a,**k:Response(self.data[65536:],206,headers))
        self.assertFalse(self.target.exists());self.assertEqual(self.target.with_suffix('.mp4.part').stat().st_size,65536)

    def test_corrupted_partial_is_not_resumed(self):
        self.first_pause();self.target.with_suffix('.mp4.part').write_bytes(b'corrupt')
        opener=Mock()
        with self.assertRaises(BError) as c:download_file(self.url,self.target,opener=opener)
        self.assertEqual(c.exception.code,'DOWNLOAD_PARTIAL_CHANGED');opener.assert_not_called()

    def test_size_limit_and_https_are_enforced(self):
        with self.assertRaises(BError):download_file('http://example.org/video',self.target)
        with self.assertRaises(BError) as c:
            download_file(self.url,self.target,max_bytes=100,opener=lambda *a,**k:Response(self.data,headers={'Content-Length':str(len(self.data))}))
        self.assertEqual(c.exception.code,'DOWNLOAD_SIZE');self.assertFalse(self.target.exists())

    def test_transient_503_has_bounded_retry(self):
        failure=urllib.error.HTTPError(self.url,503,'Unavailable',{},None)
        opener=Mock(side_effect=[failure,Response(self.data,headers={'Content-Length':str(len(self.data)),'ETag':'"v1"'})])
        with patch('nodes.asr_diarize.pipeline.downloads.time.sleep'):
            download_file(self.url,self.target,max_attempts=2,opener=opener)
        self.assertEqual(opener.call_count,2);self.assertEqual(self.target.read_bytes(),self.data)

    def test_pause_at_known_eof_completes_instead_of_requesting_invalid_range(self):
        record=download_file(self.url,self.target,pause_once_bytes=len(self.data),
            opener=lambda *a,**k:Response(self.data,headers={'Content-Length':str(len(self.data)),'ETag':'"v1"'}))
        self.assertTrue(record['complete']);self.assertEqual(self.target.read_bytes(),self.data)


@dataclass
class Word:
    word:str='test';start:float=.1;end:float=.4;probability:float=.9


@dataclass
class Segment:
    id:int;start:float;end:float;text:str;words:list


@dataclass
class Info:
    duration:float


class ChunkTests(TempCase):
    def wav(self,duration=2.5,silence=False):
        sr=16000;samples=(np.sin(2*np.pi*440*np.arange(round(sr*duration))/sr)*10000).astype('<i2')
        if silence:samples[round(1.8*sr):round(2.2*sr)]=0
        p=self.root/'audio.wav'
        with wave.open(str(p),'wb') as f:f.setparams((1,2,sr,0,'NONE','not compressed'));f.writeframes(samples.tobytes())
        return p

    def test_silence_boundary_and_exact_audio_coverage(self):
        audio=self.wav(4.2,True);plan=plan_chunks(audio,2,.5)
        self.assertEqual(plan[0]['end_boundary_method'],'quiet_rms_250_min_300ms')
        self.assertEqual(plan[0]['end_frame'],plan[1]['start_frame'])
        joined=b''
        for i,c in enumerate(plan):
            path=self.root/f'part{i}.wav';write_chunk(audio,path,c)
            with wave.open(str(path),'rb') as f:joined+=f.readframes(f.getnframes())
        with wave.open(str(audio),'rb') as f:self.assertEqual(joined,f.readframes(f.getnframes()))

    def test_continuous_speech_fallback_is_flagged(self):
        plan=plan_chunks(self.wav(),1,0)
        self.assertEqual(len(plan),3)
        self.assertEqual(plan[0]['end_boundary_method'],'hard_cut_requires_boundary_review')

    def test_global_offset_and_raw_local_records_preserved(self):
        raw={'segments':[{'id':1,'start':.1,'end':.4,'text':'test','words':[{'word':'test','start':.1,'end':.4}]}]}
        before=copy.deepcopy(raw)
        records=[({'chunk_id':'c1','start_frame':0,'sample_rate_hz':16000},raw,'c1.json'),
                 ({'chunk_id':'c2','start_frame':16000,'sample_rate_hz':16000},raw,'c2.json')]
        global_segments=globalize(records)
        self.assertEqual(raw,before);self.assertEqual([s['id'] for s in global_segments],[1,2])
        self.assertAlmostEqual(global_segments[1]['words'][0]['start'],1.1)
        self.assertEqual(global_segments[1]['chunk_segment_id'],1)

    def test_chunk_pause_resume_does_not_repeat_inference(self):
        audio=self.wav();calls=[]
        class Model:
            def transcribe(self,path,**kw):
                calls.append(path)
                return iter([Segment(1,.1,.4,'test',[Word()])]),Info(1)
        r={'chunk_seconds':1,'chunk_search_seconds':0,'runtime':{'test':'fixed'},
           'asr_chunks_per_invocation':1,'asr_time_budget_sec':30}
        for expected in [1,2]:
            with self.assertRaises(BError) as c:transcribe_chunks(self.root,audio,r,Model)
            self.assertEqual(c.exception.code,'ASR_CHUNKS_PAUSED');self.assertEqual(len(calls),expected)
        raw,meta,refs=transcribe_chunks(self.root,audio,r,Model)
        self.assertEqual(len(calls),3);self.assertEqual(meta['reused_chunks_this_invocation'],2)
        self.assertEqual(len(raw['segments']),3)
        self.assertAlmostEqual(raw['segments'][-1]['start'],2.1)
        saved=self.root/'asr/chunks/chunk_00001.raw.json';saved.write_text('{}',encoding='utf-8')
        with self.assertRaises(BError) as c:transcribe_chunks(self.root,audio,r,Model)
        self.assertEqual(c.exception.code,'CHUNK_CHANGED');self.assertEqual(len(calls),3)
