import csv
import copy
import html
import math
import json
from pathlib import Path
import re

from .common import BError, artifact, milliseconds, read_json, write_json


def build_timetable(raw, grouped, source, media, asr_meta):
    mapping={s['id']:f'seg_{i:06d}' for i,s in enumerate(raw['segments'],1)}
    segments=[]
    for s in raw['segments']:
        sid=mapping[s['id']]
        raw_start=milliseconds(s['start']);raw_end=milliseconds(s['end'])
        start=min([raw_start,*[milliseconds(w['start']) for w in s.get('words') or []]])
        end=max([raw_end,*[milliseconds(w['end']) for w in s.get('words') or []]])
        adjustment=({'reason':'enclose_preserved_word_timestamps','raw_start_ms':raw_start,'raw_end_ms':raw_end,
                     'start_delta_ms':start-raw_start,'end_delta_ms':end-raw_end}
                    if (start,end)!=(raw_start,raw_end) else None)
        segments.append({'segment_id':sid,'original_segment_id':s['id'],
                         'source_chunk_id':s.get('source_chunk_id'),
                         'chunk_segment_id':s.get('chunk_segment_id'),'raw_chunk_ref':s.get('raw_chunk_ref'),
                         'speaker_id':'SPEAKER_00' if asr_meta['speaker_mode']=='single_assumed' else None,
                         'speaker_method':'single_speaker_assumption' if asr_meta['speaker_mode']=='single_assumed' else 'unknown',
                         'start_ms':start,'end_ms':end,'timing_adjustment':adjustment,
                         'en':s['text'],'words':[{'word_id':f'{sid}_w{j:04d}',
                          'original_word_index':j,'text':w['word'],'start_ms':milliseconds(w['start']),
                          'end_ms':milliseconds(w['end']),'raw_word':copy.deepcopy(w)} for j,w in enumerate(s.get('words') or [])]})
    groups=[]
    by_id={s['original_segment_id']:s for s in segments}
    for g in grouped['sentence_groups']:
        selected=[by_id[i] for i in g['source_segment_ids']]
        start=selected[0]['start_ms'];end=selected[-1]['end_ms']
        groups.append({**g,'source_segment_ids':[mapping[i] for i in g['source_segment_ids']],
                       'original_source_segment_ids':g['source_segment_ids'],
                       'raw_group_start_sec':g['start_sec'],'raw_group_end_sec':g['end_sec'],
                       'start_ms':start,'end_ms':end,'start_sec':start/1000,'end_sec':end/1000,
                       'timing_adjusted_segment_ids':[s['segment_id'] for s in selected if s['timing_adjustment']]})
    return {'schema_version':'b-timetable-1','status':'ready_for_human_review',
            'source':source,'duration_ms':media['duration_ms'],'media_sha256':media['source_sha256'],
            'original_offset_ms':source.get('original_offset_ms',0),'asr':asr_meta,
            'verification':{'word_text_human_confirmed':False,'time_human_confirmed':False,
                            'speaker_diarization_executed':False,'sentence_groups_human_confirmed':False},
            'original_segments':copy.deepcopy(raw['segments']),
            'original_segments_coordinate_system':'globalized_from_preserved_chunk_files' if asr_meta.get('chunked') else 'original_full_audio_seconds',
            'segments':segments,'sentence_groups':copy.deepcopy(groups),
            'grouping_method':grouped['grouping_method'],
            'notes':['Sentence groups are semantic proposals, not final subtitle or TTS windows.',
                     'Speaker labels are assumptions or unknown; no diarization has run.',
                     'Use raw segment IDs/references for traceability; never overwrite original predictions.']}


def validate_timetable(bundle):
    errors=[]
    if bundle.get('schema_version')!='b-timetable-1':return ['Unsupported timetable schema']
    segments=bundle['segments'];raw=bundle['original_segments'];groups=bundle['sentence_groups']
    if not segments:errors.append('No speech segments')
    ids=[s['segment_id'] for s in segments]
    if len(set(ids))!=len(ids):errors.append('Duplicate normalized segment IDs')
    if len(raw)!=len(segments):errors.append('Original segment count changed')
    if [i for g in groups for i in g['source_segment_ids']]!=ids:errors.append('Group coverage is missing, duplicated or reordered')
    by_id={s['segment_id']:s for s in segments}
    previous=-1
    for s,original in zip(segments,raw):
        if (type(s['start_ms']) is not int or type(s['end_ms']) is not int or
            not 0<=s['start_ms']<s['end_ms']<=bundle['duration_ms']):errors.append('Invalid segment timeline')
        if s['start_ms']<previous:errors.append('Overlapping/out-of-order segments')
        previous=s['end_ms']
        if s['original_segment_id']!=original['id'] or s['en']!=original['text']:errors.append('Raw segment identity/text changed')
        raw_start=milliseconds(original['start']);raw_end=milliseconds(original['end'])
        expected_start=min([raw_start,*[milliseconds(w['start']) for w in original.get('words') or []]])
        expected_end=max([raw_end,*[milliseconds(w['end']) for w in original.get('words') or []]])
        if (s['start_ms'],s['end_ms'])!=(raw_start,raw_end):
            expected_adjustment={'reason':'enclose_preserved_word_timestamps','raw_start_ms':raw_start,'raw_end_ms':raw_end,
                                 'start_delta_ms':expected_start-raw_start,'end_delta_ms':expected_end-raw_end}
            if ((s['start_ms'],s['end_ms'])!=(expected_start,expected_end) or
                s.get('timing_adjustment')!=expected_adjustment):errors.append('Unexplained normalized segment time adjustment')
        if [w['raw_word'] for w in s['words']]!=(original.get('words') or []):errors.append('Raw words changed')
        for w in s['words']:
            if not s['start_ms']<=w['start_ms']<=w['end_ms']<=s['end_ms']:errors.append('Word outside parent segment')
            if w['start_ms']!=milliseconds(w['raw_word']['start']) or w['end_ms']!=milliseconds(w['raw_word']['end']):errors.append('Normalized word time differs from raw prediction')
    for g in groups:
        if not g['source_segment_ids'] or any(i not in by_id for i in g['source_segment_ids']):
            errors.append('Invalid group source');continue
        selected=[by_id[i] for i in g['source_segment_ids']]
        if g['start_ms']!=selected[0]['start_ms'] or g['end_ms']!=selected[-1]['end_ms']:errors.append('Group boundaries changed')
        exact=' '.join(s['en'].strip() for s in selected)
        if g['en_exact_join']!=exact:errors.append('Group exact text changed')
        if re.findall(r"[\w']+",exact.lower())!=re.findall(r"[\w']+",g['en_reading'].lower()):errors.append('Group lexical content changed')
        expected=[w['raw_word'] for s in selected for w in s['words']]
        if [w['word_data'] for w in g['words']]!=expected:errors.append('Group word trace changed')
        if g['original_source_segment_ids']!=[s['original_segment_id'] for s in selected]:errors.append('Group raw source IDs changed')
        expected_trace=[(s['original_segment_id'],w['original_word_index']) for s in selected for w in s['words']]
        if [(w['source_segment_id'],w['source_word_index']) for w in g['words']]!=expected_trace:errors.append('Word source index changed')
    return sorted(set(errors))


def export(job,bundle,media_ref):
    target=artifact(job,'timetable.json');write_json(target,bundle)
    with artifact(job,'segments.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['segment_id','original_segment_id','start_ms','end_ms','original_start_ms','original_end_ms','speaker_id','speaker_method','en','timing_adjustment'])
        for s in bundle['segments']:writer.writerow([s['segment_id'],s['original_segment_id'],s['start_ms'],s['end_ms'],s['start_ms']+bundle['original_offset_ms'],s['end_ms']+bundle['original_offset_ms'],s['speaker_id'],s['speaker_method'],s['en'],json.dumps(s.get('timing_adjustment'),ensure_ascii=False)])
    with artifact(job,'sentence-groups.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['group_id','source_segment_ids','start_ms','end_ms','en_reading','en_exact_join','reason','human_confirmed'])
        for g in bundle['sentence_groups']:writer.writerow([g['group_id'],' '.join(g['source_segment_ids']),g['start_ms'],g['end_ms'],g['en_reading'],g['en_exact_join'],g['reason'],False])
    with artifact(job,'words.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['word_id','segment_id','start_ms','end_ms','text','backend_probability'])
        for s in bundle['segments']:
            for w in s['words']:writer.writerow([w['word_id'],s['segment_id'],w['start_ms'],w['end_ms'],w['text'],w['raw_word'].get('probability')])
    rows=[]
    for g in bundle['sentence_groups']:
        selected=[s for s in bundle['segments'] if s['segment_id'] in g['source_segment_ids']]
        original='<br>'.join(html.escape(s['segment_id']+': '+s['en']) for s in selected)
        words=' '.join(f'<button data-t="{w["start_ms"]/1000}">{html.escape(w["text"])}</button>' for s in selected for w in s['words'])
        note='片段边界按已有词时间扩展；原边界与调整保留在JSON/CSV。' if g.get('timing_adjusted_segment_ids') else ''
        rows.append(f'''<tr><td>{g['group_id']}<br><button data-t="{g['start_ms']/1000}">{g['start_ms']/1000:.3f}–{g['end_ms']/1000:.3f}s</button><br>原课起点 {(g['start_ms']+bundle['original_offset_ms'])/1000:.3f}s</td><td>{original}</td><td>{html.escape(g['en_reading'])}<details><summary>原始词与时间（点击跳转）</summary>{words}</details><p>{html.escape(g['reason'])}</p><small>{note}</small></td></tr>''')
    title=f"英文台词时间表：{len(bundle['segments'])} 原片段 / {len(bundle['sentence_groups'])} 候选分组"
    attribution=html.escape(bundle['source']['attribution'])
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>英文台词时间表</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:20px auto;padding:0 16px;color:#20334a}header{position:sticky;top:0;background:white}video{width:100%;max-height:350px;background:#111}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5df;padding:10px;vertical-align:top}th{background:#edf4fa}button{cursor:pointer;margin:2px}details{margin-top:10px}</style><h1>'''+html.escape(title)+'''</h1><p>真实 LangGraph B 流程输出。英文、时间及分组待人工核验；说话人为单人假设或未知，未运行自动区分。句子分组不是最终字幕或配音窗口。</p><header><video id="v" controls src="'''+html.escape(media_ref,quote=True)+'''"></video></header><table><tr><th>分组与时间</th><th>原始分段</th><th>候选句子与词时间</th></tr>'''+''.join(rows)+'''</table><p>'''+attribution+'''</p><p>'''+html.escape(bundle['source'].get('changes',''))+'''</p><p><a href="'''+html.escape(bundle['source']['page_url'],quote=True)+'''">来源</a> | <a href="'''+html.escape(bundle['source']['license_url'],quote=True)+'''">'''+html.escape(bundle['source']['license'])+'''</a></p><script>const v=document.getElementById('v');document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{v.currentTime=Number(b.dataset.t);v.play().catch(()=>{});});</script></html>'''
    artifact(job,'review.html').write_text(page,encoding='utf-8')
    return 'timetable.json'
