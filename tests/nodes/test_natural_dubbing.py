import json
import wave
from types import SimpleNamespace

from contracts import GraphState,Segment,TranslatedSegment
from nodes.natural_dubbing import make_groups,prepare_script,synthesize_groups


def test_forward_schedule_keeps_short_acknowledgement_without_early_start():
    from nodes.natural_dubbing import schedule_window
    plan=SimpleNamespace(max_speedup=1.35,max_forward_delay_ms=500)
    short={'group_id':'ack','start_ms':31560,'original_end_ms':31680,'available_end_ms':31720}
    start,window=schedule_window(short,480,0,40000,plan)
    assert start==31560 and window>=480/1.30
    following={'group_id':'next','start_ms':31720,'original_end_ms':34640,'available_end_ms':34900}
    next_start,next_window=schedule_window(following,2800,start+window,40000,plan)
    assert 31720<next_start<=31720+500
    third={'group_id':'third','start_ms':34900,'original_end_ms':35220,'available_end_ms':36840}
    third_start,third_window=schedule_window(third,620,next_start+next_window,40000,plan)
    assert third_start>=34900 and third_start+third_window<=36840 # A later gap absorbs the delay.
    assert short['start_ms']==31560 and following['start_ms']==31720


def test_forward_schedule_rejects_excessive_delay_and_video_overrun():
    import pytest
    from nodes.natural_dubbing import schedule_window
    plan=SimpleNamespace(max_speedup=1.35,max_forward_delay_ms=500)
    group={'group_id':'long','start_ms':100,'original_end_ms':200,'available_end_ms':300}
    with pytest.raises(ValueError,match='DUB_FORWARD_DELAY_LIMIT|TTS_TEXT_TOO_LONG'):
        schedule_window(group,2000,0,10000,plan)
    with pytest.raises(ValueError,match='DUB_FORWARD_DELAY_LIMIT|TTS_TEXT_TOO_LONG'):
        schedule_window(group,480,0,300,plan)
    with pytest.raises(ValueError,match='TTS_EMPTY_AUDIO'):
        schedule_window(group,0,0,1000,plan)


def test_soft_speed_target_can_use_hard_limit_without_exceeding_delay():
    from nodes.natural_dubbing import schedule_window
    plan=SimpleNamespace(max_speedup=1.35,max_forward_delay_ms=500)
    group={'group_id':'edge','start_ms':0,'original_end_ms':900,'available_end_ms':1000}
    start,window=schedule_window(group,2000,0,5000,plan)
    assert start==0 and window==1500 and 2000/window<=1.35


def example():
    return GraphState(segments=[
        Segment(segment_id='seg_0001',speaker_id='spk_1',start_ms=0,end_ms=400,text_en='Oh no.'),
        Segment(segment_id='seg_0002',speaker_id='spk_1',start_ms=600,end_ms=1000,text_en='I came before.'),
        Segment(segment_id='seg_0003',speaker_id='spk_2',start_ms=1200,end_ms=2000,text_en='Good.')],
        reviewed_blocks=[TranslatedSegment(segment_id=f'seg_{i:04d}',block_id='blk_0001',zh_subtitle=text)
                         for i,text in enumerate(['不是','以前来过','很好'],1)])


def test_groups_keep_speaker_boundaries_and_reject_missing_group(monkeypatch):
    import pytest
    state=example();groups=make_groups(state)
    assert [g['segment_ids'] for g in groups]==[['seg_0001','seg_0002'],['seg_0003']]
    assert groups[0]['available_end_ms']==1200
    monkeypatch.setattr('nodes.natural_dubbing._text_model.request_json',lambda **kw:{'groups':[]})
    with pytest.raises(ValueError,match='遗漏'):prepare_script(state)


def test_continuous_group_is_synthesized_once_and_chunks_reconstruct_signal(tmp_path,monkeypatch):
    from utils import paths
    monkeypatch.setattr(paths,'_work_dir',tmp_path)
    for folder in ['tts','audio']:(tmp_path/folder).mkdir()
    monkeypatch.setattr('nodes.natural_dubbing._text_model.request_json',lambda **kw:{'groups':[
        {'group_id':'dub_0001','text':'不是，我以前来过。'},
        {'group_id':'dub_0002','text':'很好。'}]})
    calls=[]
    def write(path,count):
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(1000)
            f.writeframes(b'\x01\x02'*count)
    def synth(text,voice,model,rate,path):
        calls.append(text);write(path,700)
    def duration(path):
        with wave.open(str(path),'rb') as f:return round(f.getnframes()*1000/f.getframerate())
    def fit(src,dst,ms,rate,**kwargs):write(dst,ms)
    def assemble(*args):pass
    plan=SimpleNamespace(model='test',sample_rate=1000,max_speedup=1.35)
    state=example()
    result=synthesize_groups(state,plan,{'spk_1':'v1','spk_2':'v2'},synth,fit,duration,assemble)
    assert len(calls)==2 and len(result['tts_clips'])==3
    assert state.segments[1].start_ms==600
    def frames(path):
        with wave.open(str(path),'rb') as f:return f.readframes(f.getnframes())
    assert frames(tmp_path/'tts/dub_0001.wav')==frames(tmp_path/'tts/seg_0001.wav')+frames(tmp_path/'tts/seg_0002.wav')
    synthesize_groups(state,plan,{'spk_1':'v1','spk_2':'v2'},synth,fit,duration,assemble)
    assert len(calls)==2 # Reuse paid synthesis for unchanged text/voice/model.
    report=json.loads((tmp_path/'tts/alignment_report.json').read_text())
    assert all(not r['speech_trimmed'] for r in report)
