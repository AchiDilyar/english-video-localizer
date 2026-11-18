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


def test_invalid_model_cut_falls_back_per_group_and_preserves_both_languages():
    from nodes.semantic_subtitles import request_pairs
    groups=[{'group_id':'g','zh':'完整保留一句话。','en':'Keep it complete.'},
            {'group_id':'good','zh':'你好。','en':'Hello.'}]
    def model(**kwargs):
        return {'items':[{'group_id':'g','parts':[{'zh':'完整保','en':'Keep '},{'zh':'留一句话。','en':'it complete.'}]},
                         {'group_id':'good','parts':[{'zh':'你好。','en':'Hello.'}]}]}
    warnings=[]
    mapping=request_pairs(groups,model,warnings=warnings)
    assert mapping['g']==[{'zh':groups[0]['zh'],'en':groups[0]['en']}]
    assert mapping['good']==[{'zh':'你好。','en':'Hello.'}]
    assert len(warnings)==1 and warnings[0]['group_id']=='g'
    parents={'g':{'start_ms':0,'end_ms':4000,'source_segment_ids':['s'],
                  'audio_text_spans':[{'text':groups[0]['zh'],'start_ms':0,'end_ms':4000}]}}
    cues=pair_cues(groups[:1],parents,{'g':mapping['g']})
    result=paginate(cues,DisplayMetrics(320,180,strict_single_line=True))
    for lang in ['zh','en']:
        assert ''.join(c[lang] for c in result)==groups[0][lang]
        assert all('\n' not in c[lang+'_display'] for c in result)
    assert result[0]['start_ms']==0 and result[-1]['end_ms']==4000


def test_model_rewritten_english_is_discarded_not_published():
    from nodes.semantic_subtitles import request_pairs
    groups=[{'group_id':'g','zh':'我们能做到。','en':'We can do it.'}]
    result=request_pairs(groups,lambda **kwargs:{'items':[{'group_id':'g','parts':[{'zh':'我们能做到。','en':'We could do it.'}]}]})
    assert result['g'][0]['en']=='We can do it.'


@pytest.mark.parametrize('response',[None,{'items':[]},{'items':[{'group_id':'unknown','parts':[]}]}, {'items':[{'group_id':[],'parts':[]}]}])
def test_invalid_semantic_batch_falls_back_without_dropping_source(response):
    from nodes.semantic_subtitles import request_pairs
    groups=[{'group_id':'g','zh':'你好。','en':'Hello.'}];warnings=[]
    result=request_pairs(groups,lambda **kwargs:response,warnings=warnings)
    assert result=={'g':[{'zh':'你好。','en':'Hello.'}]}
    assert len(warnings)==1


def test_optional_semantic_service_failure_does_not_retry_or_block_local_display():
    from nodes.semantic_subtitles import request_pairs
    from nodes.translate_blocks._deepseek import DeepSeekError
    calls=[]
    def unavailable(**kwargs):calls.append(1);raise DeepSeekError('service unavailable')
    result=request_pairs([{'group_id':'g','zh':'你好。','en':'Hello.'}],unavailable)
    assert len(calls)==1 and result['g'][0]['en']=='Hello.'


def test_semantic_audio_boundary_rounding_keeps_positive_display_durations():
    group={'group_id':'g','zh':'一，二。','en':'One, two.'}
    parents={'g':{'start_ms':0,'end_ms':100,'source_segment_ids':['s'],
                  'audio_text_spans':[{'text':'一，','start_ms':0,'end_ms':0},{'text':'二。','start_ms':0,'end_ms':100}]}}
    pairs=[{'zh':'一，','en':'One, '},{'zh':'二。','en':'two.'}]
    cues=pair_cues([group],parents,{'g':pairs})
    assert cues[0]['start_ms']==0 and cues[0]['end_ms']==cues[1]['start_ms']==1
    assert cues[1]['end_ms']==100
