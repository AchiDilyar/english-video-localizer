import subprocess,wave
from pathlib import Path
import numpy as np
import pytest
from nodes.audio_mixing import mix_background,select_prepared_mix
from nodes.tts_align import resolve_ffmpeg


def test_real_stereo_background_mix_and_stale_dub_rejection(tmp_path):
    rate=24000;t=np.arange(2*rate)/rate
    voice=(np.sin(2*np.pi*1000*t)*.1*32767).astype('<i2')
    bed=(np.stack([np.sin(2*np.pi*200*t),np.sin(2*np.pi*400*t)],axis=1)*.02*32767).astype('<i2')
    for name,data,channels in [('dub.wav',voice,1),('background.wav',bed,2)]:
        with wave.open(str(tmp_path/name),'wb') as f:
            f.setnchannels(channels);f.setsampwidth(2);f.setframerate(rate);f.writeframes(data.tobytes())
    source=tmp_path/'source.mp4';source.write_bytes(b'source-identity')
    output=tmp_path/'mixed.wav';ffmpeg=resolve_ffmpeg()
    mix_background(tmp_path/'background.wav',tmp_path/'dub.wav',output,ffmpeg=ffmpeg,duration_sec=2,source_video=source)
    pcm=np.frombuffer(subprocess.check_output([ffmpeg,'-v','error','-i',str(output),'-f','f32le','-']),dtype='<f4').reshape(-1,2)
    assert len(pcm)==96000 and np.max(np.abs(pcm))<=.951
    frequencies=np.fft.rfftfreq(len(pcm),1/48000)
    spectral=np.abs(np.fft.rfft(pcm[:,0]));right=np.abs(np.fft.rfft(pcm[:,1]))
    for hz,spectrum in [(1000,spectral),(200,spectral),(400,right)]:
        assert spectrum[np.argmin(abs(frequencies-hz))]>10
    assert select_prepared_mix(tmp_path/'dub.wav',source)==output
    (tmp_path/'dub.wav').write_bytes(b'changed-voice')
    with pytest.raises(ValueError,match='does not match'):select_prepared_mix(tmp_path/'dub.wav',source)
