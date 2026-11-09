"""Local faster-whisper sample inference and a browser-based human review artifact."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]


def stamp(seconds):
    milliseconds = int(seconds * 1000 + 0.5)
    return f'{milliseconds//60000:02d}:{milliseconds//1000%60:02d}.{milliseconds%1000:03d}'


def srt_time(seconds):
    milliseconds = int(seconds * 1000 + 0.5)
    return f'{milliseconds//3600000:02d}:{milliseconds//60000%60:02d}:{milliseconds//1000%60:02d},{milliseconds%1000:03d}'


def review_page(segments, video_relative, summary):
    rows = []
    for i, s in enumerate(segments, 1):
        words = ' '.join(f'<button class="word" data-t="{w["start"]}">{html.escape(w["word"])}</button>' for w in s['words'] or [])
        rows.append(f'''<tr><td>{i}</td><td><button data-t="{s['start']}">{stamp(s['start'])}</button>–{stamp(s['end'])}<br>原课 {stamp(s['start']+60)}</td>
<td><input class="speaker" value="SPEAKER_00" aria-label="说话人"><small>单人假设，未做自动区分</small></td>
<td>{html.escape(s['text'])}<details><summary>词级时间：点击单词跳转</summary>{words}</details>
<textarea class="correction" placeholder="填写你的更正，或记下起止时间偏移"></textarea></td></tr>''')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>英文转写人工核对</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1200px;margin:24px auto;padding:0 18px;color:#223047}video{width:100%;max-height:420px;background:#111}header{position:sticky;top:0;background:#fff;padding:8px 0;z-index:2}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd5df;padding:10px;vertical-align:top}th{background:#edf4fa}small{display:block;color:#6a5000}.word{margin:2px}button{cursor:pointer;padding:5px}textarea{width:95%;min-height:65px;margin-top:10px}input{max-width:130px}p{margin:10px 0}</style>
<h1>英文转写人工核对</h1><p>''' + html.escape(summary) + '''</p>
<p><b>这些英文和时间是机器原始预测，尚未人工确认。</b>全部 SPEAKER_00 是单人假设，不是说话人识别结果；若听到其他声音，请修改编号并记下时间。原课时间 = 本片时间 + 60 秒。</p>
<header><video id="video" controls src="''' + html.escape(video_relative, quote=True) + '''"></video><br>
<button onclick="video.playbackRate=.75">0.75 倍</button> <button onclick="video.playbackRate=1">正常速度</button>
<button id="save">下载我的核对记录</button><span id="notice"></span></header>
<p>点击每段开始时间重听；展开词级时间可定位单词。输入更正后点击下载保存；页面关闭或刷新会丢失未下载的编辑。本页不联网、不上传记录。</p>
<table><thead><tr><th>编号</th><th>本片时间</th><th>说话人</th><th>机器英文 / 你的更正</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table>
<p>Ana Bell / MIT OpenCourseWare, 6.0001 Fall 2016. 本片为第60–105秒节选与转码。CC BY-NC-SA 4.0：<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">许可</a>。转写为新增机器预测，未作为官方参考译文。</p>
<script>const video=document.getElementById('video');document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{video.currentTime=Number(b.dataset.t);video.play().catch(()=>{});});document.getElementById('save').onclick=()=>{const rows=[...document.querySelectorAll('tbody tr')].map((r,i)=>({segment_number:i+1,speaker_id:r.querySelector('.speaker').value,correction:r.querySelector('.correction').value}));const blob=new Blob([JSON.stringify({human_review:true,rows},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='human-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),3000);document.getElementById('notice').textContent=' 已发起下载，请保留核对记录文件。';};</script></html>'''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    audio = ROOT/'jobs/B-MIT-sample-20261107/prepared/audio.wav'
    video = ROOT/'media/mit_ocw_6_0001_lecture1/mit_lecture1_0060_0105.mp4'
    from faster_whisper import WhisperModel
    start = time.perf_counter()
    model = WhisperModel(str(args.model_dir.resolve()), device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
    load_sec = time.perf_counter()-start
    inference_start = time.perf_counter()
    iterator, info = model.transcribe(str(audio), language='en', beam_size=5, word_timestamps=True,
                                      vad_filter=False, temperature=0, condition_on_previous_text=True)
    segments = []
    for segment in iterator:
        data = asdict(segment)
        segments.append(data)
        print(stamp(segment.start), stamp(segment.end), segment.text, flush=True)
    inference_sec = time.perf_counter()-inference_start
    (output/'asr.raw.json').write_text(json.dumps({'info': asdict(info), 'segments': segments}, ensure_ascii=False, indent=2), encoding='utf-8')
    with wave.open(str(audio),'rb') as wav:
        duration = wav.getnframes()/wav.getframerate()
    problems = []
    for s in segments:
        if not 0 <= s['start'] < s['end'] <= duration + .001:
            problems.append({'segment': s['id'], 'problem': 'segment bounds'})
        for w in s['words'] or []:
            if not 0 <= w['start'] <= w['end'] <= duration + .001:
                problems.append({'segment': s['id'], 'word': w['word'], 'problem': 'word bounds'})
    text = '\n'.join(f"{i:02d} | {stamp(s['start'])}–{stamp(s['end'])} | SPEAKER_00 [assumed] | {s['text'].strip()}" for i,s in enumerate(segments,1))
    (output/'transcript.txt').write_text('Machine prediction; speaker labels assumed; not human verified.\n'+text+'\n',encoding='utf-8')
    import csv
    with (output/'segments-review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['segment','start_sec','end_sec','original_start_sec','original_end_sec','speaker_id','speaker_method','machine_en','human_en','human_start_sec','human_end_sec','human_speaker','notes'])
        for i,s in enumerate(segments,1):writer.writerow([i,s['start'],s['end'],s['start']+60,s['end']+60,'SPEAKER_00','single_speaker_assumption',s['text'].strip(),'','','','',''])
    with (output/'words.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['segment','word','start_sec','end_sec','probability'])
        for i,s in enumerate(segments,1):
            for w in s['words'] or []:writer.writerow([i,w['word'],w['start'],w['end'],w['probability']])
    (output/'english.srt').write_text('\n\n'.join(f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text'].strip()}" for i,s in enumerate(segments,1))+'\n',encoding='utf-8')
    record = {'created_utc':datetime.now(timezone.utc).isoformat(),'model_dir':str(args.model_dir.resolve()),
              'device':'cpu','compute_type':'int8','cpu_threads':4,'beam_size':5,'language':'en',
              'word_timestamps':True,'vad_filter':False,'temperature':0,'condition_on_previous_text':True,
              'load_sec':load_sec,'inference_sec':inference_sec,'audio_duration_sec':duration,
              'audio_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),
              'model_files_sha256':{str(p.relative_to(args.model_dir)):hashlib.sha256(p.read_bytes()).hexdigest() for p in args.model_dir.rglob('*') if p.is_file() and '.cache' not in p.parts},
              'packages':{p:importlib.metadata.version(p) for p in ['faster-whisper','ctranslate2','av','tokenizers']},
              'segment_count':len(segments),'word_count':sum(len(s['words'] or []) for s in segments),
              'validation_problems':problems,'diarization_executed':False,'speaker_method':'single_speaker_assumption',
              'human_verified':False,'peak_vram':None,'api_calls':0,'paid_api_cost':0,'deepseek_used':False}
    download_record=args.model_dir/'download-provenance.json'
    record['model_download']=json.loads(download_record.read_text(encoding='utf-8')) if download_record.exists() else None
    record['command']=[sys.executable,*sys.argv]
    record['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    record['python']=sys.version
    (output/'execution.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    rel=os.path.relpath(video,output).replace(os.sep,'/')
    (output/'review.html').write_text(review_page(segments,rel,'本地 faster-whisper；CPU int8；英文原始转写与词时间戳。'),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False,indent=2))
    if problems or not segments:
        raise SystemExit('ASR output requires inspection; raw output retained.')


if __name__=='__main__':
    main()
