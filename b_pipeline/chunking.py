"""Silence-aware, non-overlapping PCM chunks with persistent local ASR results."""
from __future__ import annotations

import copy
from dataclasses import asdict
import time
import wave

import numpy as np

from .common import BError, artifact, digest, event, object_hash, read_json, write_json


def plan_chunks(audio, chunk_seconds=120, search_seconds=5):
    if not 1<=chunk_seconds<=300 or not 0<=search_seconds<=10:
        raise BError('CHUNK_CONFIG','Chunk target must be 1–300 seconds; search window 0–10 seconds')
    plan=[]
    with wave.open(str(audio),'rb') as wav:
        sr=wav.getframerate();total=wav.getnframes()
        if (sr,wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
            raise BError('CHUNK_AUDIO','Expected normalized 16 kHz mono PCM16')
        begin=0
        while begin<total:
            target=min(total,begin+round(chunk_seconds*sr));end=target;method='end_of_audio'
            if target<total:
                method='hard_cut_requires_boundary_review'
                lo=max(begin+sr,target-round(search_seconds*sr));hi=min(total,target+round(search_seconds*sr))
                if hi>lo:
                    wav.setpos(lo);samples=np.frombuffer(wav.readframes(hi-lo),dtype='<i2').astype(np.float64)
                    bin_frames=320;n=len(samples)//bin_frames
                    if n:
                        rms=np.sqrt(np.mean(samples[:n*bin_frames].reshape(n,bin_frames)**2,axis=1))
                        quiet=rms<250.0;runs=[];start=None
                        for i,is_quiet in enumerate([*quiet,False]):
                            if is_quiet and start is None:start=i
                            if not is_quiet and start is not None:
                                if i-start>=15:runs.append(lo+(start+i)*bin_frames//2)
                                start=None
                        if runs:
                            end=min(runs,key=lambda f:abs(f-target));method='quiet_rms_250_min_300ms'
            if not begin<end<=total:raise BError('CHUNK_BOUNDARY','Invalid sample boundary')
            plan.append({'chunk_id':f'chunk_{len(plan)+1:05d}','start_frame':begin,'end_frame':end,
                         'start_sec':begin/sr,'end_sec':end/sr,'sample_rate_hz':sr,
                         'end_boundary_method':method})
            begin=end
    return plan


def write_chunk(audio, target, chunk):
    with wave.open(str(audio),'rb') as src,wave.open(str(target),'wb') as out:
        out.setparams((1,2,16000,0,'NONE','not compressed'))
        src.setpos(chunk['start_frame']);remaining=chunk['end_frame']-chunk['start_frame']
        while remaining:
            n=min(remaining,16000*10);data=src.readframes(n)
            if len(data)!=n*2:raise BError('CHUNK_AUDIO','Truncated input WAV')
            out.writeframesraw(data);remaining-=n


def globalize(chunk_records):
    """Only shift local seconds; keep raw per-chunk predictions intact on disk."""
    result=[]
    for chunk,raw,ref in chunk_records:
        offset=chunk['start_frame']/chunk['sample_rate_hz']
        for original in raw['segments']:
            s=copy.deepcopy(original);s['chunk_segment_id']=s['id'];s['source_chunk_id']=chunk['chunk_id'];s['raw_chunk_ref']=ref
            s['id']=len(result)+1;s['start']+=offset;s['end']+=offset
            for w in s.get('words') or []:w['start']+=offset;w['end']+=offset
            result.append(s)
    return result


def transcribe_chunks(job,audio,r,model_factory):
    start=time.perf_counter();audio_hash=digest(audio)
    plan=plan_chunks(audio,r['chunk_seconds'],r['chunk_search_seconds'])
    plan_ref='asr/chunk-plan.json';write_json(artifact(job,plan_ref),{'chunks':plan,'audio_sha256':audio_hash,
        'policy':'nonoverlapping silence-aware chunks; fallback hard cuts explicitly flagged'})
    signature=object_hash({'audio_sha256':audio_hash,'runtime':r['runtime'],'chunk_seconds':r['chunk_seconds'],
                           'chunk_search_seconds':r['chunk_search_seconds'],'asr':'cpu-int8-en-beam5-temp0-wordtime-noVAD'})
    records=[];refs=[plan_ref];new_count=0;reuse_count=0;model=None;load_sec=0
    invocation_limit=r.get('asr_chunks_per_invocation')
    for chunk in plan:
        cid=chunk['chunk_id'];ref=f'asr/chunks/{cid}.raw.json';meta_ref=f'asr/chunks/{cid}.meta.json'
        out=artifact(job,ref);meta_path=artifact(job,meta_ref)
        if out.exists() or meta_path.exists():
            if not (out.exists() and meta_path.exists()):raise BError('CHUNK_INCOMPLETE','Chunk has incomplete artifacts; inspect before resume')
            meta=read_json(meta_path)
            if meta['input_signature']!=signature or meta['chunk']!=chunk or digest(out)!=meta['raw_sha256']:
                raise BError('CHUNK_CHANGED','Completed chunk/configuration changed')
            raw=read_json(out);reuse_count+=1;event(job,cid,'chunk_reused')
        else:
            if invocation_limit is not None and new_count>=invocation_limit:
                event(job,'transcribe','chunk_budget_pause',new_chunks=new_count,reused_chunks=reuse_count,next_chunk=cid)
                raise BError('ASR_CHUNKS_PAUSED','Chunk batch finished; resume to process remaining chunks')
            if time.perf_counter()-start>=r['asr_time_budget_sec']:
                raise BError('ASR_TIME_LIMIT','ASR invocation time budget reached between chunks; completed chunks retained')
            if model is None:
                t=time.perf_counter();model=model_factory();load_sec=time.perf_counter()-t
            wav_ref=f'asr/chunks/{cid}.wav';target=artifact(job,wav_ref);target.parent.mkdir(parents=True,exist_ok=True)
            write_chunk(audio,target,chunk);t=time.perf_counter()
            iterator,info=model.transcribe(str(target),language='en',beam_size=5,temperature=0,
                                            word_timestamps=True,vad_filter=False,condition_on_previous_text=True)
            raw={'info':asdict(info),'segments':[asdict(s) for s in iterator]}
            elapsed=time.perf_counter()-t
            # Zero speech is valid for an individual chunk, not for the whole film.
            write_json(out,raw)
            write_json(meta_path,{'input_signature':signature,'chunk':chunk,'raw_sha256':digest(out),
                                  'wav_sha256':digest(target),'wav_ref':wav_ref,'inference_sec':elapsed,
                                  'model_load_sec_this_chunk':load_sec if new_count==0 else 0})
            event(job,cid,'chunk_completed',inference_sec=elapsed,segment_count=len(raw['segments']))
            new_count+=1
        meta=read_json(meta_path)
        wav=artifact(job,meta['wav_ref'])
        if not wav.is_file() or digest(wav)!=meta['wav_sha256']:raise BError('CHUNK_CHANGED','Chunk audio changed')
        refs.extend([ref,meta_ref,meta['wav_ref']]);records.append((chunk,raw,ref))
    merged={'info':{'chunked':True,'duration':plan[-1]['end_sec'],'sample_rate_hz':16000,
                    'mapping':'global_seconds = chunk.start_frame / 16000 + raw_local_seconds'},
            'segments':globalize(records)}
    metas=[read_json(artifact(job,f'asr/chunks/{c[0]["chunk_id"]}.meta.json')) for c in records]
    return merged,{'load_sec_this_invocation':load_sec,'inference_sec':sum(m['inference_sec'] for m in metas),
                   'time_mapping':'global_seconds = chunk_start_frame / 16000 + raw_chunk_seconds',
                   'raw_chunks':[{'chunk_id':c['chunk_id'],'raw_ref':ref,'raw_sha256':digest(artifact(job,ref)),
                                  'start_frame':c['start_frame'],'sample_rate_hz':c['sample_rate_hz']}
                                 for c,raw,ref in records],
                   'chunk_count':len(plan),'new_chunks_this_invocation':new_count,'reused_chunks_this_invocation':reuse_count,
                   'elapsed_sec_this_invocation':time.perf_counter()-start,
                   'boundary_review_chunks':[c['chunk_id'] for c in plan if c['end_boundary_method']=='hard_cut_requires_boundary_review']},refs
