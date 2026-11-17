import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from nodes.duration_repair import measure_with_repair
from utils import paths


def group():return {'group_id':'dub_1','text':'保留40年。','start_ms':0,'original_end_ms':4000,'available_duration_ms':5000,
    'source':[{'segment_id':'s','text_en':'Keep it for 40 years.','zh_subtitle':'保留40年'}]}


def plan(**kwargs):return SimpleNamespace(min_speed=.85,min_speech_fill_ratio=.9,min_slowdown_window_ms=1000,
    max_speedup=1.35,max_forward_delay_ms=500,duration_repair_attempts=1,**kwargs)


def test_too_short_rewrites_only_this_group_and_reuses_repair_cache(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir()
    calls=[];synth=[]
    def prepare(text):
        if text not in synth:synth.append(text)
        return Path('cached.wav'),1000 if text=='保留40年。' else 3500
    def repair(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':True,'issues':[]}
        calls.append(kwargs['payload']);return {'group_id':'dub_1','text':'这件东西需要完整保留40年。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',repair)
    original=group();g=copy.deepcopy(original)
    measure_with_repair(g,plan(),prepare,lambda ms:(0,4000),{'voice':'v'})
    assert calls[0]['action']=='expand' and original['text']=='保留40年。'
    assert len(synth)==2 and '完整保留40年' in g['text']
    measure_with_repair(copy.deepcopy(original),plan(),prepare,lambda ms:(0,4000),{'voice':'v'})
    assert len(calls)==1 and len(synth)==2


def test_too_long_requests_compression_and_does_not_change_english(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir()
    g=group();source=copy.deepcopy(g['source']);calls=[]
    def repair(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':True,'issues':[]}
        calls.append(kwargs['payload']);return {'group_id':'dub_1','text':'保存40年。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',repair)
    def schedule(ms):
        if ms>5400:raise ValueError('TTS_TEXT_TOO_LONG')
        return 0,4000
    measure_with_repair(g,plan(),lambda text:(Path('x'),6000 if text=='保留40年。' else 3500),schedule,{'voice':'v'})
    assert calls[0]['action']=='compress' and g['source']==source


def test_numeric_facts_cannot_be_removed_by_lengthening(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir()
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',lambda **kw:{'group_id':'dub_1','text':'需要保存很长时间。'})
    with pytest.raises(ValueError,match='数字'):measure_with_repair(group(),plan(),lambda text:(Path('x'),1000),lambda ms:(0,4000),{})


def test_extreme_shortness_is_not_solved_by_unbounded_slowing(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir()
    p=plan();p.duration_repair_attempts=0
    with pytest.raises(ValueError,match='TTS_TEXT_TOO_SHORT'):
        measure_with_repair(group(),p,lambda text:(Path('x'),1000),lambda ms:(0,4000),{})
    report=json.loads((tmp_path/'tts/duration_repair_requests.json').read_text(encoding='utf-8'))
    assert next(iter(report.values()))['action']=='expand'


def test_actual_encoder_receipt_can_trigger_expansion_after_nominal_fit(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir();calls=[]
    def repair(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':True,'issues':[]}
        calls.append(kwargs['payload']['action']);return {'group_id':'dub_1','text':'这件东西需要完整保留40年。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',repair)
    measured=iter([{'measured_stretched_audio_ms':3000},{'measured_stretched_audio_ms':3900}])
    measure_with_repair(group(),plan(),lambda text:(Path('x'),3500),lambda ms:(0,4000),{},lambda raw,pos:next(measured))
    assert calls==['expand']


def test_rejected_semantic_repair_is_not_sent_to_tts(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir();synth=[]
    def model(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':False,'issues':['新增事实']}
        return {'group_id':'dub_1','text':'保留40年并添加未经原文提供的条件。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',model)
    def prepare(text):synth.append(text);return Path('x'),1000
    with pytest.raises(ValueError,match='SEMANTIC_REVIEW_FAILED'):
        measure_with_repair(group(),plan(),prepare,lambda ms:(0,4000),{})
    assert synth==['保留40年。']


def test_optional_shortfall_warning_preserves_original_after_rejection(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir();submitted=[]
    def model(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':False,'issues':['凑字']}
        return {'group_id':'dub_1','text':'其实真正需要保留40年。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',model)
    def prepare(text):submitted.append(text);return Path('x'),1000
    g=group();measure_with_repair(g,plan(short_duration_policy='warn'),prepare,lambda ms:(0,4000),{})
    assert g['text']=='保留40年。' and all(t==g['text'] for t in submitted)
    record=next(iter(json.loads((tmp_path/'tts/duration_repair_requests.json').read_text(encoding='utf-8')).values()))
    assert record['status']=='shortfall_warning_original_retained' and not record['semantic_review']['approved']


def test_resume_cannot_reset_approved_rewrite_limit(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir();calls=[]
    def model(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':True,'issues':[]}
        calls.append('rewrite');return {'group_id':'dub_1','text':'这件东西需要完整保留40年。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',model)
    measure_with_repair(group(),plan(),lambda text:(Path('x'),1000 if text=='保留40年。' else 3500),lambda ms:(0,4000),{})
    with pytest.raises(ValueError,match='TTS_TEXT_TOO_SHORT'):
        measure_with_repair(group(),plan(),lambda text:(Path('x'),1000),lambda ms:(0,4000),{})
    assert calls==['rewrite']


def test_exhausted_shortfall_keeps_longer_reviewed_revision(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir()
    revised='这件东西应当保留40年。'
    def model(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':True,'issues':[]}
        return {'group_id':'dub_1','text':revised}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',model)
    g=group();raw,ms,_=measure_with_repair(g,plan(short_duration_policy='warn'),
        lambda text:(Path('x'),1000 if text==group()['text'] else 2000),lambda ms:(0,4000),{})
    assert g['text']==revised and ms==2000
    record=next(iter(json.loads((tmp_path/'tts/duration_repair_requests.json').read_text(encoding='utf-8')).values()))
    assert record['status']=='shortfall_warning_reviewed_revision_retained'


def test_shortfall_does_not_keep_a_revision_with_worse_measured_duration(tmp_path,monkeypatch):
    monkeypatch.setattr(paths,'_work_dir',tmp_path);(tmp_path/'tts').mkdir()
    def model(**kwargs):
        if 'candidate_text' in kwargs['payload']:return {'group_id':'dub_1','approved':True,'issues':[]}
        return {'group_id':'dub_1','text':'这件东西应当保留40年。'}
    monkeypatch.setattr('nodes.duration_repair._text_model.request_json',model)
    g=group();_,ms,_=measure_with_repair(g,plan(short_duration_policy='warn'),
        lambda text:(Path('x'),2000 if text==group()['text'] else 1000),lambda ms:(0,4000),{})
    assert g['text']==group()['text'] and ms==2000
