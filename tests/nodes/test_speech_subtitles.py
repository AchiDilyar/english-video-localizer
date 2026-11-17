from nodes.speech_subtitles import split_words
from nodes.speech_subtitles import pair_original_english


def test_subtitle_time_comes_from_actual_audio_words_not_old_cue_start():
    words=[{'text':'很好。','start_ms':2220,'end_ms':2600},
           {'text':'你是','start_ms':2760,'end_ms':3010},
           {'text':'第一次','start_ms':3010,'end_ms':3500},
           {'text':'来巴黎吧？','start_ms':3500,'end_ms':4100}]
    cues=split_words(words)
    assert [(r['start_ms'],r['end_ms']) for r in cues]==[(2220,2600),(2760,4100)]
    assert cues[0]['zh']=='很好。'
    assert cues[1]['zh']=='你是第一次来巴黎吧？'


def test_zero_duration_suffix_remains_in_previous_cue_without_fake_time():
    cues=split_words([{'text':'你好。','start_ms':100,'end_ms':500},
                      {'text':'啊。','start_ms':500,'end_ms':500}])
    assert len(cues)==1 and cues[0]['zh']=='你好。啊。'
    assert (cues[0]['start_ms'],cues[0]['end_ms'])==(100,500)


def test_english_is_verbatim_when_two_original_sentences_share_one_spoken_cue():
    source=[{'segment_id':'seg_0001','text_en':'Oh, no.','zh_subtitle':'哦不'},
            {'segment_id':'seg_0002','text_en':"I've actually been here before.",'zh_subtitle':'我以前来过这里'},
            {'segment_id':'seg_0003','text_en':'Yes, I have addressed business groups.','zh_subtitle':'向商界演讲'},
            {'segment_id':'seg_0004','text_en':"I've addressed education groups.",'zh_subtitle':'向教育团体演讲'}]
    spoken=[{'cue_id':f's{i}','start_ms':i*1000,'end_ms':i*1000+900,'zh':text}
            for i,text in enumerate(['不是','我以前来过','还给商界和教育团体做过演讲'])]
    cues=pair_original_english(spoken,source)
    assert [r['source_segment_ids'] for r in cues]==[['seg_0001'],['seg_0002'],['seg_0003','seg_0004']]
    assert cues[2]['en']==source[2]['text_en']+'\n'+source[3]['text_en']
    assert [(r['start_ms'],r['end_ms']) for r in cues]==[(r['start_ms'],r['end_ms']) for r in spoken]


def test_multiple_chinese_audio_cues_can_share_unchanged_original_english():
    source=[{'segment_id':'seg_0001','text_en':"Yeah, I'm very excited about being here.",'zh_subtitle':'是的 来到这里我很兴奋'}]
    cues=pair_original_english([{'start_ms':100,'end_ms':400,'zh':'是的'},
                               {'start_ms':500,'end_ms':1400,'zh':'来到这里我很兴奋'}],source)
    assert len(cues)==1 and cues[0]['en']==source[0]['text_en']
    assert (cues[0]['start_ms'],cues[0]['end_ms'])==(100,1400)
