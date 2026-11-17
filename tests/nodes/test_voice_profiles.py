import json
import wave
from types import SimpleNamespace
import pytest
from nodes.voice_profiles import enroll_profiles,load_profiles


def test_authorization_scope_and_cache(tmp_path,monkeypatch):
    sample=tmp_path/'sample.wav'
    with wave.open(str(sample),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
        audio.writeframes(bytes(320000))
    source=tmp_path/'source.wav';source.write_bytes(b'source-one')
    manifest=tmp_path/'voice_profiles.json'
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            self.audio=SimpleNamespace(voices=SimpleNamespace(create=self.create))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def create(self,**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(voice_id='cosyvoice-test-speaker')
    refs={'spk_1':sample}
    with pytest.raises(PermissionError):
        enroll_profiles(source,refs,manifest,model='model',region='ap-southeast-1',client_factory=Client)
    monkeypatch.setenv('DASHSCOPE_API_KEY','fake-key')
    options=dict(model='model',region='ap-southeast-1',authorized=True,allow_network=True,client_factory=Client)
    assert enroll_profiles(source,refs,manifest,**options)=={'spk_1':'cosyvoice-test-speaker'}
    assert enroll_profiles(source,refs,manifest,**options)=={'spk_1':'cosyvoice-test-speaker'}
    assert len(calls)==1 and calls[0]['url'].startswith('data:audio/wav;base64,')
    assert 'fake-key' not in manifest.read_text()
    with pytest.raises(ValueError):load_profiles(manifest,source,'other-model','ap-southeast-1',['spk_1'])
    with pytest.raises(ValueError):load_profiles(manifest,source,'model','ap-southeast-1',['spk_2'])
    source.write_bytes(b'other-video')
    with pytest.raises(ValueError):load_profiles(manifest,source,'model','ap-southeast-1',['spk_1'])
