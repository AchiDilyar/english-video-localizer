import pytest
from contracts import Segment
from nodes.dubbing_timing import forward_windows


def test_only_forward_gap_is_available_and_last_stops_at_video_end():
    rows=[Segment(segment_id='seg_0001',speaker_id='spk_1',start_ms=1000,end_ms=1660,text_en='A'),
          Segment(segment_id='seg_0002',speaker_id='spk_2',start_ms=1920,end_ms=2140,text_en='B')]
    assert forward_windows(rows,3000)=={'seg_0001':(1000,1920),'seg_0002':(1920,3000)}
    assert rows[0].end_ms==1660
    rows[1]=rows[1].model_copy(update={'start_ms':1500})
    with pytest.raises(ValueError):forward_windows(rows,3000)


def test_global_reservation_prevents_short_next_group_being_consumed():
    from nodes.dubbing_timing import DubbingPolicy,reserve_end_limits,schedule_group,validate_final_timeline
    policy=DubbingPolicy(max_forward_delay_ms=500,repair_rounds=8,exhaustion='use_latest')
    groups=[{'group_id':'a','start_ms':0,'original_end_ms':1000,'available_end_ms':1000},
            {'group_id':'b','start_ms':1000,'original_end_ms':1100,'available_end_ms':1100},
            {'group_id':'c','start_ms':1100,'original_end_ms':2000,'available_end_ms':2000}]
    limits=reserve_end_limits(groups,2000,policy)
    cursor=0;rows=[]
    for group,raw in zip(groups,[1800,300,2000]):
        group={**group,'duration_exhausted':True}
        start,window=schedule_group(group,raw,cursor,2000,policy,end_limit=limits[group['group_id']])
        assert window>0 and start>=group['start_ms'] and start-group['start_ms']<=500
        rows.append({'group_id':group['group_id'],'start_ms':start,'end_ms':start+window})
        cursor=start+window
    validate_final_timeline(rows,2000)
    assert rows[-1]['end_ms']==2000


def test_invalid_source_timeline_is_rejected_before_any_audio_work():
    from nodes.dubbing_timing import DubbingPolicy,reserve_end_limits
    with pytest.raises(ValueError,match='DUB_INVALID_TIMELINE'):
        reserve_end_limits([{'group_id':'bad','start_ms':2000,'original_end_ms':2100}],2000,DubbingPolicy())


@pytest.mark.parametrize('rows',[
    [{'group_id':'a','start_ms':0,'end_ms':100},{'group_id':'b','start_ms':99,'end_ms':200}],
    [{'group_id':'a','start_ms':0,'end_ms':201}],
    [{'group_id':'a','start_ms':0,'end_ms':0}],
])
def test_final_audio_guard_rejects_overlap_zero_or_overrun(rows):
    from nodes.dubbing_timing import validate_final_timeline
    with pytest.raises(ValueError,match='DUB_INVALID_FINAL_TIMELINE'):
        validate_final_timeline(rows,200)


def test_display_guard_preserves_verbatim_english_and_final_bounds():
    from nodes.dubbing_timing import validate_display_cues
    rows=[{'start_ms':10,'end_ms':20,'zh':'你好。','en':'Hello.'}]
    validate_display_cues(rows,30,'Hello.')
    with pytest.raises(ValueError,match='COVERAGE'):
        validate_display_cues(rows,30,'Goodbye.')
    with pytest.raises(ValueError,match='TIMELINE'):
        validate_display_cues(rows,15,'Hello.')


def test_real_borrow_chain_reserves_short_ack_and_finishes_at_fixed_video_end():
    from nodes.dubbing_timing import DubbingPolicy,reserve_end_limits,schedule_group,validate_final_timeline
    policy=DubbingPolicy(max_forward_delay_ms=500,repair_rounds=8,exhaustion='use_latest')
    a={'group_id':'a','start_ms':0,'original_end_ms':1000,'available_end_ms':1000}
    b={'group_id':'b','start_ms':1000,'original_end_ms':1100,'available_end_ms':1100}
    c={'group_id':'c','start_ms':1100,'original_end_ms':2000,'available_end_ms':2000}
    limits=reserve_end_limits([a,b,c],2000,policy)
    x,y=schedule_group(a,1950,0,2000,policy,end_limit=limits['a'])
    assert (x,y)==(0,1500)
    with pytest.raises(ValueError,match='TTS_TEXT_TOO_LONG'):
        schedule_group(b,300,1500,2000,policy,end_limit=limits['b'])
    b['duration_exhausted']=True
    bx,by=schedule_group(b,300,1500,2000,policy,end_limit=limits['b'])
    assert (bx,by)==(1500,100)
    cx,cy=schedule_group(c,500,bx+by,2000,policy,end_limit=limits['c'])
    assert (cx,cy)==(1600,400)
    validate_final_timeline([{'group_id':k,'start_ms':s,'end_ms':s+w} for k,s,w in [('a',x,y),('b',bx,by),('c',cx,cy)]],2000)
