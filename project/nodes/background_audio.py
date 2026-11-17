"""Local Hybrid Demucs separation, retaining original stereo/time alignment.

CLI worker uses already-declared speech dependencies. No cloud audio transfer.
"""
import argparse
import hashlib
import json
import subprocess
import time
import wave
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def separate(source,folder,ffmpeg,model_dir,*,seconds=None,device='cuda',allow_download=False):
    import numpy as np
    import torch
    import torchaudio
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    torch.hub.set_dir(str(Path(model_dir).resolve()))
    key={'source_sha256':digest(source),'model':'HDEMUCS_HIGH_MUSDB_PLUS',
         'seconds':seconds,'method':'context_crop_v1','core_seconds':8,'context_seconds':1}
    receipt=folder/'separation.json'
    if receipt.exists():
        cached=json.loads(receipt.read_text(encoding='utf-8'))
        if cached.get('cache_key')==key and all((folder/name).is_file() and digest(folder/name)==cached['sha256'][name] for name in ['background.wav','vocals.wav']):return cached
    bundle=torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS
    if not allow_download and not (Path(model_dir)/'torchaudio/models/hdemucs_high_trained.pt').is_file():
        raise FileNotFoundError('Local Demucs weights missing; download must be explicitly enabled')
    started=time.perf_counter();model=bundle.get_model().eval().to(device);rate=bundle.sample_rate
    command=[str(ffmpeg),'-v','error','-y','-i',str(source),'-map','0:a:0','-vn','-ac','2','-ar',str(rate)]
    if seconds is not None:command+=['-t',str(seconds)]
    command+=['-c:a','pcm_s16le',str(folder/'source-stereo.wav')]
    subprocess.run(command,check=True)
    with wave.open(str(folder/'source-stereo.wav'),'rb') as f:
        samples=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,2).T.astype(np.float32)/32768
    mix=torch.from_numpy(samples);mean=mix.mean();std=mix.std()
    if std<1e-8:raise ValueError('Source is silent')
    normalized=(mix-mean)/std
    vocal_index=model.sources.index('vocals');background=torch.zeros_like(mix);vocals=torch.zeros_like(mix)
    core=rate*8;context=rate;length=mix.shape[-1]
    torch.manual_seed(0)
    with torch.inference_mode():
        for start in range(0,length,core):
            end=min(length,start+core);left=max(0,start-context);right=min(length,end+context)
            output=model(normalized[:,left:right].unsqueeze(0).to(device))[0].cpu()
            output=output[:,:,start-left:end-left]*std
            vocals[:,start:end]=output[vocal_index]
            background[:,start:end]=output.sum(dim=0)-output[vocal_index]+mean
            print(f'separated {end/rate:.2f}/{length/rate:.2f}s',flush=True)
    def write(name,value):
        if not torch.isfinite(value).all():raise ValueError('Non-finite separation output')
        # Float WAV preserves stem amplitude without independent normalization.
        data=value.T.contiguous().numpy().astype('<f4').tobytes()
        subprocess.run([str(ffmpeg),'-v','error','-y','-f','f32le','-ar',str(rate),'-ac','2','-i','pipe:0',
                        '-c:a','pcm_f32le',str(folder/name)],input=data,check=True)
    write('background.wav',background);write('vocals.wav',vocals)
    result={'cache_key':key,'sample_rate':rate,'channels':2,'frames':length,'duration_sec':length/rate,
            'device':str(device),'torch':torch.__version__,'torchaudio':torchaudio.__version__,
            'elapsed_sec':time.perf_counter()-started,'sources':model.sources,
            'background_method':'sum of non-vocal model stems, not original audio mixed back in',
            'rms_source':float(mix.square().mean().sqrt()),'rms_background':float(background.square().mean().sqrt()),
            'rms_vocals':float(vocals.square().mean().sqrt()),
            'reconstruction_rmse':float((mix-background-vocals).square().mean().sqrt()),
            'sha256':{name:digest(folder/name) for name in ['background.wav','vocals.wav']},
            'human_audition_confirmed':False,'limitation':'Music-trained separator; residual speech/reverb and loss of some ambient sounds remain possible'}
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--ffmpeg',type=Path,required=True)
    parser.add_argument('--model-dir',type=Path,required=True);parser.add_argument('--seconds',type=float)
    parser.add_argument('--device',default='cuda');parser.add_argument('--allow-download',action='store_true')
    args=parser.parse_args()
    print(json.dumps(separate(args.source,args.output,args.ffmpeg,args.model_dir,seconds=args.seconds,
                             device=args.device,allow_download=args.allow_download),ensure_ascii=False))
