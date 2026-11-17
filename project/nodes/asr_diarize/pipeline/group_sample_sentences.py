"""Group a specific reviewed ASR sample without rewriting original segments/words.

Uses a versioned, sample-bound grouping proposal; not a general sentence detector.
"""
import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time


def group_bundle(raw, plan, source_bytes):
    if hashlib.sha256(source_bytes).hexdigest() != plan['source_asr_sha256']:
        raise ValueError('Grouping plan belongs to a different ASR source')
    segments = raw['segments']
    ids = [s['id'] for s in segments]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate source segment ID')
    cover = [i for g in plan['groups'] for i in g['source_segment_ids']]
    if cover != ids:
        raise ValueError('Groups must cover every source segment exactly once in order')
    by_id = {s['id']: s for s in segments}
    groups = []
    for n, proposal in enumerate(plan['groups'], 1):
        selected = [by_id[i] for i in proposal['source_segment_ids']]
        if any(a['end'] > b['start'] for a,b in zip(selected,selected[1:])):
            raise ValueError('Overlapping source segments require manual inspection')
        exact = ' '.join(s['text'].strip() for s in selected)
        reading = proposal.get('reading_text',exact)
        # Optional reading form can change only punctuation/whitespace/case, never words.
        tokens = lambda t: re.findall(r"[\w']+",t.lower())
        if tokens(exact) != tokens(reading):
            raise ValueError('Reading text changes lexical content')
        words = [{'source_segment_id':s['id'],'source_word_index':j,'word_data':copy.deepcopy(w)}
                 for s in selected for j,w in enumerate(s.get('words') or [])]
        groups.append({'group_id':f'sentence_{n:04d}',
                       'source_segment_ids':proposal['source_segment_ids'],
                       'start_sec':selected[0]['start'],'end_sec':selected[-1]['end'],
                       'speaker_id':plan['speaker_id'],'speaker_method':plan['speaker_method'],
                       'en_exact_join':exact,'en_reading':reading,
                       'reading_edit': 'punctuation_or_case_only' if reading!=exact else None,
                       'reason':proposal['reason'],'boundary_note':proposal.get('boundary_note'),
                       'human_grouping_confirmed':False,'words':words})
    return {'kind':'b_local_sentence_group_proposal','source_asr_sha256':plan['source_asr_sha256'],
            'grouping_method':'sample_specific_plan_not_general_algorithm',
            'original_segments':copy.deepcopy(segments),'sentence_groups':groups,
            'raw_recognition_rerun':False,'subtitle_or_dub_windows_changed':False}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--asr-json',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); start=time.perf_counter()
    source=args.asr_json.read_bytes(); raw=json.loads(source)
    plan_bytes=args.plan.read_bytes(); plan=json.loads(plan_bytes)
    bundle=group_bundle(raw,plan,source)
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'sentence-groups.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
    import csv
    with (args.output/'sentence-groups.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['group_id','source_segment_ids','start_sec','end_sec','en_exact_join','en_reading','reason','boundary_note','human_grouping_confirmed'])
        for g in bundle['sentence_groups']:
            writer.writerow([g[k] for k in ['group_id','source_segment_ids','start_sec','end_sec','en_exact_join','en_reading','reason','boundary_note','human_grouping_confirmed']])
    rows=[]
    for g in bundle['sentence_groups']:
        old='<br>'.join(f"原段 {s['id']}：{html.escape(s['text'])}" for s in bundle['original_segments'] if s['id'] in g['source_segment_ids'])
        rows.append(f'''<tr><td>{g['group_id']}<br>原段 {g['source_segment_ids']}<br><button data-start="{g['start_sec']}">{g['start_sec']:.3f}–{g['end_sec']:.3f} 秒</button></td><td>{old}</td><td>{html.escape(g['en_reading'])}<p>{html.escape(g['reason'])}</p><small>{g['boundary_note'] or ''}</small></td></tr>''')
    rel=os.path.relpath(args.video.resolve(),args.output.resolve()).replace(os.sep,'/')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>句子分组对照</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:24px auto;padding:0 16px;color:#20334a}video{width:100%;max-height:350px;background:#111}header{position:sticky;top:0;background:white}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5df;padding:12px;vertical-align:top}th{background:#edf4fa}small{color:#8a5200}button{cursor:pointer}</style><h1>18 个原始片段 → 11 个候选句子分组</h1><p>原始英文、片段和148个词时间均保留。右侧是供翻译理解的候选分组，不是已经确认的字幕或配音窗口。SPEAKER_00 仍为单人假设。片头片尾可能不完整，未补造内容。</p><header><video controls id="v" src="'''+html.escape(rel,quote=True)+'''"></video></header><p>点击时间重听。仅原段14+15的阅读版本调整标点和大小写，原始文本仍在左侧和JSON中。</p><table><tr><th>来源与时间</th><th>保留的原始分段</th><th>整理后候选 / 原因</th></tr>'''+''.join(rows)+'''</table><p>Ana Bell / MIT OpenCourseWare, 6.0001 Fall 2016. 第60–105秒节选；转写与分组为新增处理。<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">CC BY-NC-SA 4.0</a>。</p><script>const v=document.getElementById('v');document.querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>{v.currentTime=Number(b.dataset.start);v.play().catch(()=>{});});</script></html>'''
    (args.output/'comparison.html').write_text(page,encoding='utf-8')
    record={'source_sha256':hashlib.sha256(source).hexdigest(),'plan_sha256':hashlib.sha256(plan_bytes).hexdigest(),
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'original_segment_count':len(raw['segments']),'group_count':len(bundle['sentence_groups']),
            'word_count':sum(len(g['words']) for g in bundle['sentence_groups']),
            'elapsed_sec':time.perf_counter()-start,'asr_calls':0,'paid_api_calls':0,
            'command':[sys.executable,*sys.argv]}
    (args.output/'execution.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
