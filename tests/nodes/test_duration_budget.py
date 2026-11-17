from contracts import GraphState,Segment
from nodes.translate_blocks._duration_budget import budgets_for,spoken_chars


def test_budget_reads_forward_time_and_counts_spoken_characters():
    state=GraphState(segments=[
        Segment(segment_id='seg_0001',speaker_id='spk_1',start_ms=0,end_ms=1000,text_en='First.'),
        Segment(segment_id='seg_0002',speaker_id='spk_2',start_ms=2000,end_ms=2200,text_en='Good.')])
    budgets=budgets_for(state)
    assert budgets['seg_0001']['available_duration_ms']==2000
    assert budgets['seg_0001']['target_zh_chars']==8
    assert budgets['seg_0002']['target_zh_chars']==1
    assert spoken_chars('你好， 世界！')==4
