"""Local AudioSet event candidates, guarded against recognized English words."""
import argparse,json,subprocess
from pathlib import Path
import numpy as np


def pcm(path,ffmpeg,rate=16000,channels=1):
    raw=subprocess.check_output([str(ffmpeg),'-v','error','-i',str(path),'-ar',str(rate),'-ac',str(channels),'-f','f32le','-'])
    return np.frombuffer(raw,dtype='<f4').copy().reshape(-1,channels)


def features(source,output,ffmpeg,intervals=None):
    import torch
    from torchaudio.compliance.kaldi import fbank
    x=pcm(source,ffmpeg)[:,0];rows=[];times=[]
    torch.set_num_threads(4)
    windows=intervals if intervals is not None else [(max(0,c-1.5),min(len(x)/16000,c+1.5)) for c in np.arange(.5,len(x)/16000,.5)]
    for a,b in windows:
        start=max(0,round(a*16000));end=min(len(x),round(b*16000))
        segment=torch.from_numpy(x[start:end].copy());segment-=segment.mean()
        fb=fbank(segment[None],htk_compat=True,sample_frequency=16000,use_energy=False,
                 window_type='hanning',num_mel_bins=128,dither=0,frame_shift=10)
        padded=torch.zeros(1024,128);padded[:min(1024,len(fb))]=fb[:1024]
        rows.append(((padded+4.2677393)/(4.5689974*2)).numpy());times.append([start/16000,end/16000])
    np.savez_compressed(output,features=np.stack(rows),times=np.array(times))


def classify(features_file,model_dir,output):
    import onnxruntime as ort
    options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(Path(model_dir)/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    data=np.load(features_file);config=json.loads((Path(model_dir)/'config.json').read_text())
    labels=config['id2label'];rows=[]
    event_ids=[int(i) for i,name in labels.items() if any(word in name.lower() for word in ['laugh','giggl','chuckl','snicker','sigh','cough','sneez','gasp','throat clearing'])]
    speech_ids=[int(i) for i,name in labels.items() if name.lower() in {'speech','conversation','narration, monologue'}]
    for i,feature in enumerate(data['features']):
        logits=session.run(None,{session.get_inputs()[0].name:feature[None].astype(np.float32)})[0][0]
        probs=1/(1+np.exp(-np.clip(logits,-50,50)));event=max(event_ids,key=lambda j:probs[j])
        top=np.argsort(probs)[-5:][::-1]
        rows.append({'start':float(data['times'][i,0]),'end':float(data['times'][i,1]),
            'event':labels[str(event)],'score':float(probs[event]),'speech_score':float(max(probs[j] for j in speech_ids)),
            'top':[{'label':labels[str(j)],'score':float(probs[j])} for j in top]})
        if i%50==0:print('classified',i,'/',len(data['features']),flush=True)
    Path(output).write_text(json.dumps({'model':'MIT AudioSet AST; ONNX quantized conversion','windows':rows},ensure_ascii=False,indent=2),encoding='utf-8')


def guarded_intervals(windows,words,*,threshold=.2,padding=.08,speech_ratio=1.0):
    candidates=sorted((r['start'],r['end']) for r in windows if r['score']>=threshold and r['score']>=r['speech_score']*speech_ratio)
    spans=[]
    for start,end in candidates:
        if spans and start<=spans[-1][1]:spans[-1][1]=max(end,spans[-1][1])
        else:spans.append([start,end])
    for word in words:
        left=max(0,word['start']-padding);right=word['end']+padding;remaining=[]
        for start,end in spans:
            if right<=start or left>=end:remaining.append([start,end]);continue
            if start<left:remaining.append([start,left])
            if right<end:remaining.append([right,end])
        spans=remaining
    return [(round(a,3),round(b,3)) for a,b in spans if b-a>=.12]


def restore_nonverbal(background,vocals,intervals,output,ffmpeg,*,gain=.8):
    from .background_audio import digest
    if not 0<=gain<=1:raise ValueError('Nonverbal gain must be 0–1')
    rate=44100;bed=pcm(background,ffmpeg,rate,2);voice=pcm(vocals,ffmpeg,rate,2)
    if len(bed)!=len(voice):raise ValueError('Background/vocal stem duration mismatch')
    mask=np.zeros(len(bed),dtype=np.float32)
    for start,end in intervals:
        left=max(0,round(start*rate));right=min(len(mask),round(end*rate))
        if right<=left:raise ValueError('Invalid nonverbal interval')
        envelope=np.ones(right-left,dtype=np.float32);fade=min(round(.03*rate),len(envelope)//2)
        if fade:
            ramp=(1-np.cos(np.linspace(0,np.pi,fade)))/2
            envelope[:fade]=ramp;envelope[-fade:]=ramp[::-1]
        mask[left:right]=np.maximum(mask[left:right],envelope)
    result=bed+voice*mask[:,None]*gain
    subprocess.run([str(ffmpeg),'-v','error','-y','-f','f32le','-ar',str(rate),'-ac','2','-i','pipe:0',
                    '-c:a','pcm_f32le',str(output)],input=result.astype('<f4').tobytes(),check=True)
    receipt={'original_background_sha256':digest(background),'original_vocals_sha256':digest(vocals),
        'output_sha256':digest(output),'intervals_sec':intervals,'gain':gain,'speech_guard_padding_sec':.08,
        'fade_ms':30,'method':'AudioSet event proposals minus recognized English word intervals',
        'human_audition_confirmed':False,'limitation':'Conservative event proposals, not isolated nonverbal ground truth; speech-overlapping events may be excluded'}
    Path(output).with_suffix('.events.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['features','classify']);p.add_argument('--source',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--ffmpeg',default='.tools/ffmpeg/bin/ffmpeg.exe')
    p.add_argument('--features',type=Path);p.add_argument('--model-dir',type=Path)
    p.add_argument('--intervals',type=Path)
    a=p.parse_args()
    if a.stage=='features':features(a.source,a.output,a.ffmpeg,json.loads(a.intervals.read_text())['intervals'] if a.intervals else None)
    else:classify(a.features,a.model_dir,a.output)
