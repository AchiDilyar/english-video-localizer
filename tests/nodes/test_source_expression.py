import json
import wave
import numpy as np
import pytest
from types import SimpleNamespace
from nodes.source_expression import describe
from nodes.voice_profiles import digest,inherit_verified_excerpt

def test_source_hints_and_verified_excerpt(tmp_path):
    source=tmp_path/'source.wav';child=tmp_path/'child.wav'
    samples=(np.sin(np.arange(32000)*2*np.pi*120/16000)*4000).astype('<i2').tobytes()
    for path,data in [(source,samples),(child,samples[:32000])]:
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(data)
    hints=describe(source,0,1000,'Are you sure?')
    assert '提问' in hints['instruction'] and hints['language_hints']==['zh']
    assert hints['voiced_pitch_frames']>0
    registry=tmp_path/'parent.json';out=tmp_path/'child.json'
    registry.write_text(json.dumps({'source_sha256':digest(source),'voices':{'one':{'voice_id':'same'}}}))
    inherit_verified_excerpt(source,child,registry,out)
    result=json.loads(out.read_text())
    assert result['voices']['one']['voice_id']=='same' and result['source_sha256']==digest(child)
    with wave.open(str(child),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(bytes(32000))
    with pytest.raises(ValueError,match='PCM differs'):inherit_verified_excerpt(source,child,registry,out)


def test_expression_changes_invalidate_raw_cache(tmp_path,monkeypatch):
    from nodes.natural_dubbing import raw_cache_path
    from utils import paths
    monkeypatch.setattr(paths,'_work_dir',tmp_path)
    plan=SimpleNamespace(model='cosyvoice-v3-flash',sample_rate=24000)
    group={'text':'你好。'}
    original=raw_cache_path(group,'same-voice',plan)
    expressive=raw_cache_path({**group,'conditioning':{'instruction':'自然询问。'}},'same-voice',plan)
    assert original!=expressive
