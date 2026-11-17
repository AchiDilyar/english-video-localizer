"""Local source-acoustic cues; heuristic delivery hints, not emotion recognition."""
import hashlib
import wave
import numpy as np


def describe(source, start_ms, end_ms, english):
    with wave.open(str(source),'rb') as audio:
        rate=audio.getframerate()
        if audio.getsampwidth()!=2 or audio.getnchannels()!=1:raise ValueError('Source expression requires mono PCM16')
        audio.setpos(round(start_ms*rate/1000))
        pcm=audio.readframes(round((end_ms-start_ms)*rate/1000))
    x=np.frombuffer(pcm,dtype='<i2').astype(float)/32768
    energy=[];pitch=[]
    size=round(rate*.04)
    for at in range(0,len(x)-size+1,round(rate*.02)):
        frame=x[at:at+size];rms=float(np.sqrt(np.mean(frame*frame)));energy.append(rms)
        if rms<.008:continue
        frame=(frame-frame.mean())*np.hanning(size)
        spectrum=np.fft.rfft(frame,n=2*size)
        ac=np.fft.irfft(spectrum*np.conj(spectrum))[:size]
        lo,hi=round(rate/350),round(rate/65)
        lag=lo+int(np.argmax(ac[lo:hi]))
        if ac[0]>0 and ac[lag]/ac[0]>.45:pitch.append(rate/lag)
    spread=float(np.std(12*np.log2(np.array(pitch)/np.median(pitch)))) if len(pitch)>4 else None
    instruction='保留参考原声的个人音色和口语习惯，像面对面聊天，不用播音、朗诵或翻译解说腔。'
    if '?' in english:instruction+='自然地提问。'
    assert sum(2 if ord(c)>127 else 1 for c in instruction)<=100
    return {'instruction':instruction,'language_hints':['zh'],'method':'source_voice_conversation_v2',
            'source_pcm_sha256':hashlib.sha256(pcm).hexdigest(),'source_start_ms':start_ms,'source_end_ms':end_ms,
            'pitch_spread_semitones':spread,'voiced_pitch_frames':len(pitch),
            'rms_mean':sum(energy)/max(1,len(energy)), 'emotion_or_similarity_verified':False}
