"""Move bounded residual padding into existing phrase pauses, never cut speech."""
import wave
import numpy as np


def distribute(path,window_ms,*,max_extra_per_pause_ms=300,tail_ms=150):
    with wave.open(str(path),'rb') as f:
        params=f.getparams();pcm=f.readframes(f.getnframes())
    rate=params.framerate
    if params.nchannels!=1 or params.sampwidth!=2:raise ValueError('Pause placement needs mono PCM16')
    x=np.frombuffer(pcm,dtype='<i2');step=max(1,rate//100)
    available=max(0,round(window_ms*rate/1000)-len(x)-round(tail_ms*rate/1000))
    if not available:return {'distributed_pause_ms':0,'pause_insertions':[]}
    rms=np.array([np.sqrt(np.mean(x[i:i+step].astype(float)**2)) for i in range(0,len(x),step)])
    threshold=min(200,max(40,float(np.percentile(rms,70))*.12))
    quiet=rms<threshold;gaps=[];start=None
    for i,value in enumerate(list(quiet)+[False]):
        if value and start is None:start=i
        if not value and start is not None:
            if 4<=i-start<=40 and start*step>rate*.3 and i*step<len(x)-rate*.3:gaps.append(((start+i)*step//2,i-start))
            start=None
    gaps=sorted(sorted(gaps,key=lambda g:g[1],reverse=True)[:8])
    total=min(available,len(gaps)*round(max_extra_per_pause_ms*rate/1000))
    if not gaps:return {'distributed_pause_ms':0,'pause_insertions':[]}
    chunks=[];previous=0;insertions=[];remaining=total
    for i,(at,_) in enumerate(gaps):
        count=remaining//(len(gaps)-i);remaining-=count
        chunks.extend([pcm[previous*2:at*2],bytes(count*2)]);previous=at
        insertions.append({'at_before_ms':round(at*1000/rate),'added_ms':round(count*1000/rate)})
    chunks.append(pcm[previous*2:])
    with wave.open(str(path),'wb') as f:f.setparams(params);f.writeframes(b''.join(chunks))
    return {'distributed_pause_ms':round(total*1000/rate),'pause_insertions':insertions}
