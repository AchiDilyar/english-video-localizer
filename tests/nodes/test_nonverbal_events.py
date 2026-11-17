from nodes.nonverbal_events import guarded_intervals

def test_laughter_restoration_excludes_spoken_words_and_faint_candidates():
    windows=[{'start':0,'end':3,'event':'Laughter','score':.8,'speech_score':.2},
             {'start':5,'end':6,'event':'Laughter','score':.01,'speech_score':.7}]
    words=[{'start':0,'end':1},{'start':2,'end':3}]
    result=guarded_intervals(windows,words)
    assert result==[(1.08,1.92)]
    assert all(b<=1.92 for a,b in result)


def test_restoration_does_not_change_samples_outside_allowed_interval(tmp_path):
    import wave
    import numpy as np
    from nodes.nonverbal_events import restore_nonverbal,pcm
    from nodes.tts_align import resolve_ffmpeg
    rate=44100;t=np.arange(rate)/rate
    for name,hz in [('background.wav',200),('vocals.wav',500)]:
        data=(np.stack([np.sin(2*np.pi*hz*t)]*2,axis=1)*2000).astype('<i2')
        with wave.open(str(tmp_path/name),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(rate);f.writeframes(data.tobytes())
    ffmpeg=resolve_ffmpeg();output=tmp_path/'restored.wav'
    restore_nonverbal(tmp_path/'background.wav',tmp_path/'vocals.wav',[(.3,.6)],output,ffmpeg)
    before=pcm(tmp_path/'background.wav',ffmpeg,rate,2);after=pcm(output,ffmpeg,rate,2)
    assert np.array_equal(before[:round(.3*rate)],after[:round(.3*rate)])
    assert np.array_equal(before[round(.6*rate):],after[round(.6*rate):])
    assert np.max(abs(after[round(.35*rate):round(.55*rate)]-before[round(.35*rate):round(.55*rate)]))>.01
