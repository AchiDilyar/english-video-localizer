"""Isolated Community-1 worker: explicit model download, then local waveform inference.

Run with .venv-community1/Scripts/python.exe, outside the working ASR environment.
No credentials in arguments, output, or receipts; Hugging Face manages local auth.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
import wave

os.environ['PYANNOTE_METRICS_ENABLED']='0'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['DO_NOT_TRACK']='1'
os.environ['OTEL_SDK_DISABLED']='true'

MODEL='pyannote/speaker-diarization-community-1'


def canonical_turns(annotation,duration_ms):
    raw=sorted((float(part.start),float(part.end),str(speaker)) for part,_,speaker in annotation.itertracks(yield_label=True))
    labels={};turns=[]
    for start,end,speaker in raw:
        start=max(0,round(start*1000));end=min(duration_ms,round(end*1000))
        if start>=end:continue
        if speaker not in labels:labels[speaker]=f'speaker_{len(labels)+1:03d}'
        turns.append({'start_ms':start,'end_ms':end,'speaker_id':labels[speaker]})
    if not turns:raise ValueError('No usable speaker turns')
    return turns,list(labels.values())


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare-model',action='store_true')
    p.add_argument('--allow-model-download',action='store_true');p.add_argument('--cache-dir',default='models/community-1-hf-cache')
    p.add_argument('--audio');p.add_argument('--output');p.add_argument('--num-speakers',type=int)
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    a=p.parse_args();cache=Path(a.cache_dir).resolve();manifest=cache/'local-model.json'
    if a.prepare_model:
        if not a.allow_model_download:raise SystemExit('Explicit --allow-model-download required')
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import GatedRepoError
        try:path=snapshot_download(MODEL,cache_dir=str(cache))
        except GatedRepoError:raise SystemExit('MODEL_ACCESS_REQUIRED: accept the model conditions using your own Hugging Face account') from None
        weights={str(f.relative_to(path)):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path(path).rglob('*') if f.is_file()}
        manifest.write_text(json.dumps({'repo_id':MODEL,'snapshot':path,'files_sha256':weights},indent=2),encoding='utf-8')
        print('Model downloaded; local provenance saved');return
    if not a.audio or not a.output:p.error('--audio and --output required for inference')
    if not manifest.is_file():raise SystemExit('LOCAL_MODEL_MISSING: prepare the authorized model first')
    if a.num_speakers is not None and not 1<=a.num_speakers<=32:p.error('Speaker count out of range')
    os.environ['HF_HUB_OFFLINE']='1';os.environ['HF_HUB_CACHE']=str(cache)
    provenance=json.loads(manifest.read_text(encoding='utf-8'));snapshot=Path(provenance['snapshot'])
    for name,sha in provenance['files_sha256'].items():
        if hashlib.sha256((snapshot/name).read_bytes()).hexdigest()!=sha:raise SystemExit('MODEL_CHANGED')
    import numpy as np
    import torch
    from pyannote.audio import Pipeline
    path=Path(a.audio).resolve();output=Path(a.output).resolve()
    if output.exists():raise SystemExit('OUTPUT_EXISTS: choose a new result path')
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise SystemExit('Expected mono PCM16 16kHz WAV')
        frames=wav.getnframes();samples=np.frombuffer(wav.readframes(frames),dtype=np.int16).astype(np.float32)/32768
    if a.device=='cuda' and not torch.cuda.is_available():raise SystemExit('CUDA_UNAVAILABLE: no silent CPU fallback')
    started=time.perf_counter();torch.set_num_threads(4)
    if a.device=='cuda':torch.cuda.reset_peak_memory_stats()
    pipeline=Pipeline.from_pretrained(str(snapshot));pipeline.to(torch.device(a.device))
    options={'num_speakers':a.num_speakers} if a.num_speakers is not None else {}
    progress_seen={}
    def progress(step,*args,**kwargs):
        total=kwargs.get('total');completed=kwargs.get('completed')
        bucket=int(4*completed/total) if total and completed is not None else -1
        if progress_seen.get(step)!=bucket:
            progress_seen[step]=bucket;print('[community-1]',step,str(bucket*25)+'%' if bucket>=0 else 'started/completed',flush=True)
    result=pipeline({'waveform':torch.from_numpy(samples).unsqueeze(0),'sample_rate':16000},hook=progress,**options)
    if a.device=='cuda':torch.cuda.synchronize()
    annotation=getattr(result,'exclusive_speaker_diarization',None)
    if annotation is None:raise SystemExit('Exclusive diarization output missing; do not silently substitute another method')
    turns,ids=canonical_turns(annotation,round(frames/16))
    data={'turns':turns,'speaker_ids':ids,'metadata':{'engine':'pyannote-community-1','output_kind':'exclusive_speaker_diarization',
        'version':importlib.metadata.version('pyannote.audio'),'torch_version':torch.__version__,'device':a.device,
        'gpu_name':torch.cuda.get_device_name() if a.device=='cuda' else None,
        'gpu_peak_allocated_bytes':torch.cuda.max_memory_allocated() if a.device=='cuda' else None,
        'worker_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'audio_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'duration_ms':round(frames/16),
        'model_snapshot':str(snapshot),'elapsed_sec':time.perf_counter()-started,'num_speakers_requested':a.num_speakers,
        'num_speakers_detected':len(ids),'human_confirmed':False,'audio_uploaded':False,'speaker_embeddings_persisted':False}}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps({'speakers':len(ids),'turns':len(turns),'elapsed_sec':data['metadata']['elapsed_sec']}))


if __name__=='__main__':main()
