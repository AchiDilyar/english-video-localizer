"""Long-video speaker diagnostics and listening anchors; not ground-truth scoring."""
import argparse
from collections import defaultdict
import html
from pathlib import Path
from b_pipeline.common import read_json,write_json,digest


def main():
    p=argparse.ArgumentParser();p.add_argument('job');p.add_argument('--source-job',required=True)
    p.add_argument('--source-receipt',required=True);a=p.parse_args()
    job=Path(a.job);source=Path(a.source_job);table=read_json(job/'timetable.json');prior=read_json(source/'timetable.json')
    receipt=read_json(a.source_receipt)
    assert len(table['sentences'])==len(prior['sentences'])
    assert all(tuple(x[k] for k in ['sentence_id','start_ms','end_ms','en'])==tuple(y[k] for k in ['sentence_id','start_ms','end_ms','en']) for x,y in zip(table['sentences'],prior['sentences']))
    duration=table['duration_ms'];turns=table['diarization']['turns'];metadata=table['diarization']['metadata']
    assert metadata['duration_ms']==duration and metadata['audio_sha256']==digest(job/'audio.wav')
    assert all(0<=t['start_ms']<t['end_ms']<=duration for t in turns)
    if metadata.get('output_kind')=='exclusive_speaker_diarization':
        assert all(x['end_ms']<=y['start_ms'] for x,y in zip(turns,turns[1:]))
    by_speaker=defaultdict(list)
    for turn in turns:by_speaker[turn['speaker_id']].append(turn)
    rows_by_speaker=defaultdict(list)
    for row in table['sentences']:
        if row['speaker_id']:rows_by_speaker[row['speaker_id']].append(row)
    stats=[]
    for speaker in table['diarization']['speaker_ids']:
        periods=by_speaker[speaker]
        stats.append({'speaker_id':speaker,'turn_count':len(periods),'speech_ms':sum(t['end_ms']-t['start_ms'] for t in periods),
                      'assigned_sentences':len(rows_by_speaker[speaker]),'first_ms':min(t['start_ms'] for t in periods),
                      'last_ms':max(t['end_ms'] for t in periods)})
    bins=[]
    for start in range(0,duration,600000):
        end=min(duration,start+600000);amounts=defaultdict(int)
        for turn in turns:
            amount=max(0,min(end,turn['end_ms'])-max(start,turn['start_ms']))
            if amount:amounts[turn['speaker_id']]+=amount
        bins.append({'start_ms':start,'end_ms':end,'speech_ms_by_speaker':dict(amounts)})
    report={'source':receipt,'input_duration_ms':duration,'sentence_count':len(table['sentences']),
            'speaker_metadata':metadata,'speaker_summary':stats,'ten_minute_bins':bins,
            'speaker_assignment':table['review']['speaker_assignment'],'original_text_ids_times_unchanged':True,
            'structural_errors':table['review']['structural_errors'],'human_review_count':table['review']['sentences_needing_human_review'],
            'untimed_count':len(table['review']['untimed_utterances']),'execution':table['execution'],
            'human_speaker_accuracy_verified':False,'DER_measured':False,
            'interpretation':'Persistent anonymous labels and temporal coverage are diagnostics, not proof that the same real person retains one label.'}
    write_json(job/'long-multiperson-verification.json',report)
    summary_rows=[];anchors=[]
    for stat in stats:
        sid=stat['speaker_id'];summary_rows.append('<tr><td>'+sid+'</td><td>'+str(stat['assigned_sentences'])+'</td><td>'+f'{stat["speech_ms"]/1000:.1f}'+'</td><td>'+f'{stat["first_ms"]/60000:.1f}–{stat["last_ms"]/60000:.1f}'+'</td></tr>')
        rows=rows_by_speaker[sid]
        # Early/middle/late occurrences help a human check long-range consistency.
        if rows:
            for index in sorted(set([0,len(rows)//2,len(rows)-1])):
                row=rows[index];anchors.append('<tr><td>'+sid+'</td><td><button data-t="'+str(row['start_ms']/1000)+'">'+f'{row["start_ms"]/60_000:.2f} 分钟'+'</button></td><td>'+html.escape(row['en'])+'</td></tr>')
    chapter_buttons=' '.join('<button data-t="'+str(b['start_ms']/1000)+'">'+str(b['start_ms']//60000)+' 分钟</button>' for b in bins)
    credit='Wiki In Africa — '+receipt['title']+'. YouTube source: '+receipt['url']+'. License as reported by YouTube: '+receipt['license']+'. Changes: machine transcript, anonymous speaker labels and time tables. Recording duration preserved; no excerpt or spliced replacement.'
    (job/'ATTRIBUTION.txt').write_text(credit,encoding='utf-8')
    (job/'review.html').write_text((job/'review.html').read_text(encoding='utf-8').replace('<script>','<p>'+html.escape(credit)+'</p><script>'),encoding='utf-8')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>完整多人长视频验证</title><style>body{font:16px/1.6 system-ui;max-width:1250px;margin:20px auto;padding:16px}header{position:sticky;top:0;background:white}video{width:100%;max-height:380px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px}button{padding:7px;cursor:pointer}</style><h1>完整多人长视频：说话人核对入口</h1><p>'''+html.escape(receipt['title'])+'''。完整处理，没有用短片拼接。编号为模型匿名聚类，不代表已人工确认姓名或人数；同一编号跨时段出现也不证明真人一致。请回听下面各人的早/中/晚台词，检查是否串人。</p><p><a href="review.html">完整逐句时间表</a> · <a href="'''+html.escape(receipt['url'],quote=True)+'''">原 YouTube 视频</a></p><header><video id="v" controls src="source/video.mp4"></video><p>'''+chapter_buttons+'''</p></header><h2>模型统计</h2><table><tr><th>匿名编号</th><th>归属台词数</th><th>检测说话秒数</th><th>首次–末次出现 / 分钟</th></tr>'''+''.join(summary_rows)+'''</table><h2>按人抽查：早 / 中 / 晚</h2><table><tr><th>模型编号</th><th>播放位置</th><th>机器转写</th></tr>'''+''.join(anchors)+'''</table><p>'''+html.escape(credit)+'''</p><script>const v=document.getElementById('v');document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{v.currentTime=Number(b.dataset.t);v.play().catch(()=>{});});</script></html>'''
    (job/'long-speaker-review.html').write_text(page,encoding='utf-8')
    (job/'long-speaker-review-script.js').write_text(page.split('<script>')[1].split('</script>')[0],encoding='utf-8')
    print({'duration_ms':duration,'sentence_count':len(table['sentences']),'speakers':len(stats),'assignment':report['speaker_assignment'],'human_accuracy_verified':False})


if __name__=='__main__':main()
