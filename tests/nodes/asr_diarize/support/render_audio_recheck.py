"""Render text differences plus final-video playback for local ASR review."""
import argparse
import difflib
import html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
from nodes.asr_diarize.pipeline.common import read_json


def main():
    p=argparse.ArgumentParser();p.add_argument('job');a=p.parse_args();job=Path(a.job)
    if not job.resolve().is_relative_to((ROOT/'tests/tmp').resolve()):raise ValueError('Copy the task into tests/tmp before auditing')
    request=read_json(job/'request.json');old=read_json(Path(request['parent_job'])/'timetable.json')
    table=read_json(job/'timetable.json');report=table['review']['audio_recheck'];old_rows={r['sentence_id']:r for r in old['sentences']}
    # Include the prior pass, then overwrite repeated targets with their latest review.
    records={r['sentence_id']:r for r in old['review'].get('audio_recheck',{}).get('records',[])}
    records.update({r['sentence_id']:r for r in report['records']})
    cards=[]
    for record in records.values():
        before=record['before'];after=record.get('candidate','');tokens=[]
        for kind,first,last,newfirst,newlast in difflib.SequenceMatcher(None,before.split(),after.split(),autojunk=False).get_opcodes():
            if kind=='equal':tokens.append(html.escape(' '.join(after.split()[newfirst:newlast])))
            else:
                if kind in ['delete','replace']:tokens.append('<del>'+html.escape(' '.join(before.split()[first:last]))+'</del>')
                if kind in ['insert','replace']:tokens.append('<ins>'+html.escape(' '.join(after.split()[newfirst:newlast]))+'</ins>')
        row=old_rows.get(record['sentence_id'])
        if row is None:row=next(r for r in old['sentences'] if r['sentence_id'].startswith(record['sentence_id']+'_r'))
        label='已暂写入修订表，仍需听音确认' if record['status']=='provisionally_applied_insertion_only' else '原文保留；复识别候选仅供核对'
        cards.append('<article id="'+record['sentence_id']+'"><h2>'+record['sentence_id']+'</h2><button data-t="'+str(max(0,row['start_ms']/1000-2))+'">播放附近音频</button><p>'+label+'：'+html.escape(record['status'])+'</p><p>原文：'+html.escape(before)+'</p><p>复识别差异：'+' '.join(tokens)+'</p></article>')
    video=next((job/'source').glob('video.*'))
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>疑似残句音频复识别核对</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:auto;padding:20px}header{position:sticky;top:0;background:white}video{width:100%;max-height:330px}article{border-bottom:1px solid #bbb;padding:15px}ins{background:#cfeeda}del{background:#ffe0df}button{padding:8px;cursor:pointer}</style><h1>疑似残句音频复识别核对</h1><p>绿色表示局部复识别新增的词；红色表示与原文不一致的词。两种设置来自同一模型，不等于人工确认。未通过安全检查的候选没有写入修订时间表。点击按钮听原视频。</p><p><a href="review.html">修订版全片台词表</a></p><header><video id="video" controls src="source/'''+html.escape(video.name,quote=True)+'''"></video></header>'''+''.join(cards)+'''<script>const v=document.getElementById('video');document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{v.currentTime=Number(b.dataset.t);v.play().catch(()=>{});});</script></html>'''
    (job/'audio-recheck-review.html').write_text(page,encoding='utf-8')
    print({'unique_targets':len(records),'provisional_repairs':sum(r['status']=='provisionally_applied_insertion_only' for r in records.values())})


if __name__=='__main__':main()
