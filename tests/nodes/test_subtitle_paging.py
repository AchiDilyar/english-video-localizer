import copy
import re
import pytest
from nodes.subtitle_paging import DisplayMetrics,clauses,paginate


def test_punctuation_parser_preserves_abbreviations_decimals_and_quotes():
    text='Dr. Smith paid 3.14 dollars, and met O.J. at 12:30. "Really?" Yes.'
    parts=clauses(text)
    assert ''.join(parts)==text
    assert parts[0]=='Dr. Smith paid 3.14 dollars, '
    assert 'O.J. at 12:30.' in parts[1]
    assert parts[2]=='"Really?" '


def test_long_bilingual_cue_is_paged_only_at_punctuation_without_mutation():
    cue={'cue_id':'c','start_ms':100,'end_ms':12100,
        'zh':'我们保留完整的意思，字幕只在标点处分片，配音继续保持原来的连续表达。',
        'en':'We preserve the complete meaning, subtitles change only at punctuation, and the original continuous dubbing stays intact.',
        'source_segment_ids':['seg_1']}
    before=copy.deepcopy(cue);metrics=DisplayMetrics(640,360)
    result=paginate([cue],metrics)
    assert len(result)>1 and cue==before
    assert ''.join(r['zh'] for r in result)==cue['zh']
    assert ''.join(r['en'] for r in result)==cue['en']
    assert all(r['zh'].rstrip().endswith(('，','。')) and r['en'].rstrip().endswith((',','.')) for r in result[:-1])
    assert result[0]['start_ms']==100 and result[-1]['end_ms']==12100
    assert all(a['end_ms']==b['start_ms'] for a,b in zip(result,result[1:]))


def test_unpunctuated_clause_remains_one_cue_with_at_most_two_visual_lines():
    cue={'start_ms':0,'end_ms':8000,'zh':'这是一个不能为了字幕宽度而被切成两个时间片的完整分句'*3,
         'en':'This is one unpunctuated clause which must stay complete even if its visual display needs two lines '*2}
    metrics=DisplayMetrics(1280,720);result=paginate([cue],metrics)
    assert len(result)==1
    for lang in ['zh','en']:
        lines=result[0][lang+'_display'].splitlines()
        assert len(lines)<=2
        font=metrics.font(result[0][lang+'_font_size'])
        assert all(font.getlength(line)<=metrics.limit for line in lines)


def test_mismatched_language_clause_counts_do_not_duplicate_english():
    cue={'start_ms':0,'end_ms':5000,'zh':'第一部分很长而且完整，第二部分也必须完整，最后一部分仍保留。',
         'en':'One indivisible English clause corresponding to all three Chinese clauses without internal punctuation'}
    result=paginate([cue],DisplayMetrics(1280,720))
    assert len(result)==1 and result[0]['en']==cue['en']


def test_tiny_timing_is_not_expanded_by_pagination():
    result=paginate([{'start_ms':10,'end_ms':11,'zh':'好。','en':'Good.'}],DisplayMetrics(1280,720))
    assert result[0]['end_ms']==11


def test_english_prefers_bounded_single_line_adjustment():
    metrics=DisplayMetrics(1280,720);text='This complete English clause should preferably remain on one line.'
    metrics.limit=metrics.measure(text,'en')*.9
    display,size,warnings=metrics.layout(text,'en')
    assert '\n' not in display and display==text
    assert size>=round(metrics.sizes['en']*.8)
    assert 'english_single_line_with_bounded_font_adjustment' in warnings


def test_punctuation_without_following_space_preserves_exact_english():
    english='This is a long complete clause,'*3+'this is another complete clause.'
    cue={'start_ms':0,'end_ms':12000,'zh':'完整保留中文分句，完整保留后面的分句，最后仍然完整。','en':english}
    rows=paginate([cue],DisplayMetrics(1280,720))
    assert ''.join(row['en'] for row in rows)==english


def test_existing_asr_cut_inside_chinese_clause_is_removed_before_paging():
    from nodes.subtitle_paging import coalesce_incomplete_parents
    rows=[{'source_group_id':'g','start_ms':0,'end_ms':1000,'zh':'这是完整的一句话，你','en':'First sentence.'},
          {'source_group_id':'g','start_ms':1000,'end_ms':2000,'zh':'知道吗？','en':'You know?'}]
    merged=coalesce_incomplete_parents(rows)
    assert len(merged)==1 and merged[0]['zh']=='这是完整的一句话，你知道吗？'
    result=paginate(rows,DisplayMetrics(1280,720))
    assert not any(c['zh'].endswith('你') for c in result)


def test_page_boundary_uses_observed_audio_span_instead_of_uniform_time():
    from types import SimpleNamespace
    first='完整的第一个分句，';second='第二个完整的分句。'
    cue={'start_ms':0,'end_ms':10000,'zh':first+second,
        'en':'The first complete clause, the second complete clause.',
        'audio_text_spans':[{'text':first,'start_ms':0,'end_ms':700},
                            {'text':second,'start_ms':700,'end_ms':10000}]}
    metrics=SimpleNamespace(limit=100,measure=lambda text,lang:len(text)*10,layout=lambda text,lang:(text,20,[]))
    result=paginate([cue],metrics)
    assert len(result)==2 and result[0]['end_ms']==result[1]['start_ms']==700
