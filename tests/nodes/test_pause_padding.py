import wave
import numpy as np
from nodes.pause_padding import distribute

def test_padding_moves_only_into_existing_pauses_without_losing_samples(tmp_path):
    rate=16000;tone=(np.sin(np.arange(6400)*2*np.pi*150/rate)*6000).astype('<i2')
    original=np.concatenate([tone,np.zeros(1600,dtype='<i2'),tone,np.zeros(1600,dtype='<i2'),tone])
    path=tmp_path/'speech.wav'
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(original.tobytes())
    report=distribute(path,2000)
    with wave.open(str(path),'rb') as f:result=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
    assert np.array_equal(original[original!=0],result[result!=0])
    assert 0<report['distributed_pause_ms']<=600
    assert all(0<p['added_ms']<=300 for p in report['pause_insertions'])
    assert len(result)/rate<=2


def test_existing_long_pause_is_not_extended(tmp_path):
    rate=16000;tone=(np.sin(np.arange(6400)*2*np.pi*150/rate)*6000).astype('<i2')
    original=np.concatenate([tone,np.zeros(rate,dtype='<i2'),tone,np.zeros(1600,dtype='<i2'),tone])
    path=tmp_path/'speech.wav'
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(original.tobytes())
    receipt=distribute(path,3000)
    assert receipt['pause_insertions']
    assert all(not 400<=r['at_before_ms']<=1400 for r in receipt['pause_insertions'])
