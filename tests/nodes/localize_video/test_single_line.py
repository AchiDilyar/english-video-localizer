import re
import pytest
from nodes.localize_video.e_single_line import split_pair
from nodes.subtitle_paging import DisplayMetrics,paginate


@pytest.mark.parametrize('pair',[
 {'zh':'我们要怎样在推动它继续向前发展的同时，仍然保持我们自身的那种认同感？',
  'en':'and how do you maintain the sense itself while pushing it forward '},
 {'zh':'而且你自己也被看作美国黑人群体中的重要人物，',
  'en':'and as much as you yourself is seen as an important figure among black people in America, '},
])
def test_previous_two_line_examples_become_sequential_one_line_pages(pair):
    # These reported examples use the refined preset, whose font determines the cuts.
    metrics=DisplayMetrics(1280,720,strict_single_line=True,style_id='refined')
    cue={**pair,'start_ms':1000,'end_ms':7000,'semantic_pair_locked':True}
    result=paginate([cue],metrics)
    assert len(result)>=2
    for lang in ['zh','en']:
        assert ''.join(r[lang] for r in result)==pair[lang]
        assert all('\n' not in r[lang+'_display'] for r in result)
        assert all(metrics.font(r[lang+'_font_size']).getlength(r[lang+'_display'])<=metrics.limit for r in result)
    assert result[0]['start_ms']==1000 and result[-1]['end_ms']==7000
    assert all(a['end_ms']==b['start_ms'] for a,b in zip(result,result[1:]))


def test_unbreakable_token_fails_instead_of_wrapping_or_losing_text():
    with pytest.raises(ValueError,match='UNBREAKABLE'):
        split_pair({'zh':'完整中文句子。','en':'X'*1000},DisplayMetrics(1280,720,strict_single_line=True))


def test_single_line_mode_cannot_bypass_pagination_gate():
    from nodes.subtitle_cover import SubtitleCoverOptions
    with pytest.raises(ValueError,match='requires paginate'):
        SubtitleCoverOptions(strict_single_line=True,paginate=False)
