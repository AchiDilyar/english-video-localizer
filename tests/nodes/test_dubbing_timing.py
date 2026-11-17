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
