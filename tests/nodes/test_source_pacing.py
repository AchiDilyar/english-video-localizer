from pathlib import Path
from types import SimpleNamespace
import pytest
from nodes.source_pacing import prepare_paced_audio

def test_short_speech_returned_for_text_expansion_without_model_slowdown(tmp_path):
    group={'group_id':'g','text':'保留原话。','start_ms':0,'original_end_ms':25000,
           'conditioning':{'instruction':'自然交谈。'}}
    plan=SimpleNamespace(source_pacing=True,min_speed=.95);calls=[];lengths={}
    def cache(item,*args):return tmp_path/str(item['conditioning']['rate'])
    def synth(text,voice,model,sr,path,**kwargs):
        calls.append(kwargs['conditioning']['rate']);lengths[path]=round(14780/calls[-1]);path.touch()
    plan.model='model';plan.sample_rate=24000
    raw,ms=prepare_paced_audio(group,group['text'],'voice',plan,synth,lengths.__getitem__,cache)
    assert calls==[1.0] and ms==14780
    assert group['conditioning']['rate']==1.0
    assert group['text']=='保留原话。'

def test_previous_slow_model_rate_is_not_reused_or_multiplied(tmp_path):
    group={'group_id':'g','start_ms':0,'original_end_ms':25000,'conditioning':{'rate':.65}}
    plan=SimpleNamespace(source_pacing=True,min_speed=.95,model='m',sample_rate=24000)
    calls=[]
    prepare_paced_audio(group,'原稿','v',plan,lambda *a,**k:(calls.append(k['conditioning']['rate']),a[4].touch()),lambda p:10000,
                       lambda g,*a:tmp_path/str(g['conditioning']['rate']))
    assert calls==[1.0] and group['conditioning']['rate']==1.0
