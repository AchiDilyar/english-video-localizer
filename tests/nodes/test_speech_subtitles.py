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


def test_cross_group_sentence_is_locally_retimed_before_restoring_script(tmp_path,monkeypatch):
    import json
    from contracts import GraphState,Segment,TranslatedSegment
    from nodes.speech_subtitles import create_bilingual_cues
    from utils import paths
    monkeypatch.setattr(paths,'_work_dir',tmp_path)
    (tmp_path/'tts').mkdir();(tmp_path/'subtitles').mkdir()
    scripts=[{'group_id':'a','segment_ids':['seg_0001'],'text':'你好。'},
             {'group_id':'b','segment_ids':['seg_0002'],'text':'自从上次见你之后，你拿了金球奖。'}]
    reports=[{'group_id':'a','segment_ids':['seg_0001'],'start_ms':0,'end_ms':1000},
             {'group_id':'b','segment_ids':['seg_0002'],'start_ms':1000,'end_ms':3000}]
    (tmp_path/'tts/dubbing_script.json').write_text(json.dumps(scripts),encoding='utf-8')
    (tmp_path/'tts/alignment_report.json').write_text(json.dumps(reports),encoding='utf-8')
    state=GraphState(segments=[Segment(segment_id='seg_0001',speaker_id='spk_1',start_ms=0,end_ms=1000,text_en='Hello.'),
                              Segment(segment_id='seg_0002',speaker_id='spk_1',start_ms=1000,end_ms=3000,text_en='Since we last met, you won.')],
                     reviewed_blocks=[TranslatedSegment(segment_id='seg_0001',block_id='blk_0001',zh_subtitle=scripts[0]['text']),
                                      TranslatedSegment(segment_id='seg_0002',block_id='blk_0001',zh_subtitle=scripts[1]['text'])])
    monkeypatch.setattr('nodes.speech_subtitles.recognize_final_audio',lambda *args:{'audio_sha256':'fake','cues':[
        {'cue_id':'speech_0001','start_ms':200,'end_ms':1400,'zh':'你好。自从上次见你之后，'},
        {'cue_id':'speech_0002','start_ms':1500,'end_ms':2900,'zh':'你拿了金球奖。'}]})
    requested=[]
    def refine(rows,*args):
        requested.extend(row['group_id'] for row in rows)
        return {row['group_id']:[{'cue_id':'local_'+row['group_id'],'start_ms':row['start_ms']+20,
                                  'end_ms':row['end_ms']-20,'zh':scripts[i]['text'],
                                  'alignment_method':'local_group_ASR','warnings':[]}] for i,row in enumerate(rows)}
    monkeypatch.setattr('nodes.speech_alignment.refine_groups',refine)
    cues=create_bilingual_cues(state,'unused-local-model')
    assert requested==['a','b']
    assert cues[1]['start_ms']==1020 and cues[1]['zh'].startswith('自从')
    assert 'cross_group_ASR_sentence_relocalized_on_final_group_audio' in cues[1]['warnings']
