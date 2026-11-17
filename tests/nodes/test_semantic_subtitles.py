import pytest
from nodes.semantic_subtitles import literal_parts,validate_parts,pair_cues
from nodes.subtitle_paging import DisplayMetrics,paginate

def test_no_new_word_or_punctuation_can_enter_immutable_english():
    with pytest.raises(ValueError,match='coverage'):literal_parts('We can do it.', ['We could do it.'])
    assert literal_parts('We can  do it.',['We can','do it.'])==['We can  ','do it.']
    with pytest.raises(ValueError,match='splits'):literal_parts('walking',['walk','ing'])

def test_matching_semantics_are_locked_against_length_repagination():
    group={'group_id':'g','zh':'我们是谁，我们该怎么办。','en':'Who we are, and what we should do.'}
    pairs=validate_parts(group,[{'zh':'我们是谁，','en':'Who we are, '},{'zh':'我们该怎么办。','en':'and what we should do.'}])
    parents={'g':{'start_ms':0,'end_ms':4000,'source_segment_ids':['s'],
        'audio_text_spans':[{'text':'我们是谁，','start_ms':0,'end_ms':1500},{'text':'我们该怎么办。','start_ms':1500,'end_ms':4000}]}}
    cues=pair_cues([group],parents,{'g':pairs});display=paginate(cues,DisplayMetrics(1280,720))
    assert [(r['zh'],r['en']) for r in display]==[(r['zh'],r['en']) for r in cues]
    assert display[0]['end_ms']==display[1]['start_ms']==1500

def test_illegal_chinese_mid_clause_cut_is_rejected():
    group={'zh':'完整保留一句话。','en':'Keep it complete.'}
    with pytest.raises(ValueError,match='punctuation'):
        validate_parts(group,[{'zh':'完整保','en':'Keep '},{'zh':'留一句话。','en':'it complete.'}])
