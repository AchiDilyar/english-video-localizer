"""V2: one complete video → reviewed sentence-only timestamps, max two hours.

No application audio chunks. Native ASR segment/word alignments stay in memory and
are never put in files, logs, cache, or LangGraph checkpoint state.
"""
from dataclasses import asdict
import csv
import copy
import html
import importlib.metadata
import logging
import os
from pathlib import Path
import shutil
import sys
import time
import wave
from typing import TypedDict

from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.sqlite import SqliteSaver
from nodes.probe_input import media as b_media
from .common import BError,artifact,digest,event,object_hash,read_json,write_json,milliseconds
from .video_inputs import resolve_input,download_input
from .sentence_rules import sentences_from_words,sentence_audit,validate_sentence_table

ROOT=Path(__file__).resolve().parents[4]
logger=logging.getLogger(__name__)


class SentenceState(TypedDict,total=False):
    job_dir:str
    request:dict
    source:dict
    media_ref:str
    audio_ref:str
    duration_ms:int
    source_meta:dict
    table:dict
    status:str


def fingerprint(model_dir):
    model=Path(model_dir)
    files=['model.bin','config.json','tokenizer.json','vocabulary.txt']
    if any(not (model/n).is_file() for n in files):raise BError('MODEL_UNAVAILABLE','Local Whisper model is incomplete')
    return {'model_files':{n:digest(model/n) for n in files},
            'model_download':read_json(model/'download-provenance.json') if (model/'download-provenance.json').exists() else None,
            'code':{p.name:digest(p) for p in (ROOT/'project/nodes/asr_diarize/pipeline').glob('*.py')},
            'binaries_sha256':{name:digest(b_media.tool_path(name)) for name in ['ffmpeg','ffprobe']},
            'packages':{n:importlib.metadata.version(n) for n in ['faster-whisper','ctranslate2','av','spacy','en-core-web-sm','yt-dlp','langgraph']}}


def _resolve(state):
    return {'source':resolve_input(state['request']['input_ref'])}


def _acquire(state):
    r=state['request'];job=state['job_dir'];folder=artifact(job,'source')
    receipt=folder/'download.json'
    if receipt.exists():
        meta=read_json(receipt);p=folder/meta['file']
        if not p.is_file() or digest(p)!=meta['sha256']:raise BError('ARTIFACT_CHANGED','Downloaded media changed')
    else:
        p,meta=download_input(r['input_ref'],folder,allow_network=r['allow_network'],
                             max_duration_sec=r['max_duration_sec'],max_bytes=r['max_source_bytes'],
                             download_timeout_sec=r['download_timeout_sec'],node_path=r['node_path'])
    return {'media_ref':str(p.relative_to(Path(job))),'source_meta':meta}


def _prepare(state):
    job=state['job_dir'];r=state['request'];media=artifact(job,state['media_ref'])
    info=b_media.inspect(media,b_media.tool_path('ffprobe'),r['audio_stream'],r['video_stream'])
    duration=info['duration_ms']
    if not duration or duration>r['max_duration_sec']*1000+100:raise BError('DURATION_LIMIT','Input exceeds the configured limit (maximum 7200 seconds)')
    if info['video_origin_sec'] is None or info['audio_start_sec'] is None:raise BError('TIMELINE_UNKNOWN','Cannot reliably establish the video timeline')
    target=artifact(job,'audio.wav')
    if target.exists():
        receipt=artifact(job,'media.json')
        if receipt.exists():
            saved=read_json(receipt)
            if saved['video_sha256']==digest(media) and saved['audio_sha256']==digest(target) and saved['duration_ms']==duration:
                return {'audio_ref':'audio.wav','duration_ms':duration}
        raise BError('OUTPUT_EXISTS','Partial audio preparation needs inspection before retry')
    command=[b_media.tool_path('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin','-n',
             '-copyts','-protocol_whitelist','file,pipe','-i',str(media),'-map',f"0:{info['audio_stream_index']}",'-vn',
             '-af',f"asetpts=PTS-({info['video_origin_sec']})/TB,aresample=16000:async=1:first_pts=0,apad,atrim=end_sample={duration*16}",
             '-ar','16000','-ac','1','-c:a','pcm_s16le',str(target)]
    b_media.run(command,timeout=600)
    with wave.open(str(target),'rb') as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth(),wav.getnframes())!=(16000,1,2,duration*16):
            raise BError('AUDIO_INVALID','Normalized WAV has unexpected properties')
    # Deliberately omit raw ffprobe stream timestamps and command/filter time details.
    write_json(artifact(job,'media.json'),{'duration_ms':duration,'audio_sample_rate':16000,
               'audio_channels':1,'video_sha256':digest(media),'audio_sha256':digest(target)})
    return {'audio_ref':'audio.wav','duration_ms':duration}


def _recognize_sentence(state):
    from faster_whisper import WhisperModel
    import spacy
    r=state['request'];job=state['job_dir'];started=time.perf_counter()
    model=WhisperModel(r['model_dir'],device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    load=time.perf_counter()-started;t=time.perf_counter()
    # Exactly one transcribe call for the complete audio; no external splitting.
    stream,info=model.transcribe(str(artifact(job,state['audio_ref'])),language='en',beam_size=5,
                                 temperature=0,word_timestamps=True,vad_filter=False,condition_on_previous_text=True)
    words=[];count=0
    for segment in stream:
        if not segment.words and segment.text.strip():raise BError('WORD_ALIGNMENT_MISSING','Cannot time sentence text without alignment')
        words.extend({'word':w.word,'start':w.start,'end':w.end} for w in segment.words or [])
        count+=1
        if count%100==0:logger.info('ASR internal decoder results processed (not saved): %d',count)
    inference=time.perf_counter()-t
    nlp=spacy.load('en_core_web_sm',disable=['ner']);nlp.max_length=3000000
    semantic=r.get('semantic_review',{'provider':'none'})
    reviewer=None
    if semantic['provider']=='deepseek':
        from .semantic_review import DeepSeekHTTP
        reviewer=DeepSeekHTTP(allow_network=semantic['allow_network'],max_calls=semantic['max_calls'])
        if reviewer.model!=semantic.get('model') or reviewer.base_url!=semantic.get('base_url'):
            raise BError('SEMANTIC_CONFIG_CHANGED','Semantic model/endpoint changed; create a new task')
    sentences,review=sentences_from_words(words,nlp,semantic_reviewer=reviewer)
    # Discard alignment before any durable output/checkpoint update.
    word_count=len(words);del words,stream,model
    table={'schema_version':'b-sentences-2','duration_ms':state['duration_ms'],
           'source':state['source_meta'],'sentences':sentences,'review':review,
           'verification':{'human_confirmed':False,'automatic_diarization_executed':False,
                           'sentence_semantics_guaranteed':False},
           'execution':{'engine':'faster-whisper','language':'en','device':'cpu','compute_type':'int8',
                        'model_load_sec':load,'inference_sec':inference,'transcribe_calls':1,
                        'external_audio_chunks':0,'internal_decoder_results_not_persisted':count,
                        'aligned_word_count_used_in_memory':word_count,'raw_asr_timestamps_persisted':False,
                        'paid_api_calls':getattr(reviewer,'calls',0),'deepseek_used':bool(getattr(reviewer,'calls',0))}}
    return {'table':table}


def _review(state):
    import spacy
    table=copy.deepcopy(state['table']);nlp=spacy.load('en_core_web_sm',disable=['ner'])
    # Second check uses sentence text only; no original ASR alignment is available here.
    for sentence in table['sentences']:
        extra=sentence_audit(sentence['en'],nlp)
        sentence['review_issues']=sorted(set(sentence['review_issues']+extra))
        sentence['review_status']='needs_human_review' if sentence['review_issues'] else 'automatic_checks_passed'
    errors=validate_sentence_table(table)
    table['review']['structural_errors']=errors
    table['review']['sentences_needing_human_review']=sum(bool(s['review_issues']) for s in table['sentences'])
    table['status']='blocked_validation' if errors else 'ready_for_human_review'
    return {'table':table,'status':table['status']}


def _export(state):
    job=state['job_dir'];table=state['table'];write_json(artifact(job,'timetable.json'),table)
    with artifact(job,'sentences.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['sentence_id','start_ms','end_ms','speaker_id','en','review_status','review_issues','human_correction'])
        for s in table['sentences']:writer.writerow([s['sentence_id'],s['start_ms'],s['end_ms'],s['speaker_id'],s['en'],s['review_status'],'; '.join(s['review_issues']),''])
    with artifact(job,'untimed-review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['en','after_sentence_id','reason','human_start_ms','human_end_ms'])
        for item in table['review'].get('untimed_utterances',[]):writer.writerow([item['en'],item['after_sentence_id'],item['reason'],'',''])
    def stamp(ms):return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    artifact(job,'english.srt').write_text('\n\n'.join(f"{i}\n{stamp(s['start_ms'])} --> {stamp(s['end_ms'])}\n{s['en']}" for i,s in enumerate(table['sentences'],1))+'\n',encoding='utf-8')
    rows=[]
    for s in table['sentences']:
        issue='待复核：'+', '.join(s['review_issues']) if s['review_issues'] else '自动审查通过，仍可人工核对'
        rows.append(f'<tr><td>{s["sentence_id"]}</td><td><button data-t="{s["start_ms"]/1000}">{s["start_ms"]/1000:.3f}–{s["end_ms"]/1000:.3f} 秒</button></td><td>{html.escape(s["speaker_id"] or "未确定")}</td><td>{html.escape(s["en"])}</td><td>{html.escape(issue)}</td></tr>')
    pending=''.join('<li>'+html.escape(item['en'])+'（在 '+html.escape(item['after_sentence_id'] or '视频开头')+' 之后；对齐没有可用时长，请听辨补定时间）</li>' for item in table['review'].get('untimed_utterances',[]))
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>完整句子台词时间表</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:20px auto;padding:0 16px;color:#20334a}header{position:sticky;top:0;background:white}video{width:100%;max-height:350px;background:#111}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5df;padding:10px;vertical-align:top}th{background:#edf4fa}button{cursor:pointer}</style><h1>完整句子台词时间表</h1><p>只显示最终句子起止时间，不保存原始ASR片段或词时间。句法分句后已进行从句/延续表达审查；标记项需人工核对。说话人身份未识别。自动审查不保证所有口语表达均为完整语法句。</p><header><video id="v" controls src="'''+html.escape(state['media_ref'],quote=True)+'''"></video></header><p>需人工补定时间的短语：</p><ul>'''+pending+'''</ul><table><tr><th>句子</th><th>最终时间</th><th>英文</th><th>审查</th></tr>'''+''.join(rows)+'''</table><p>来源：'''+html.escape(table['source'].get('title',''))+'''。本地处理；分享前保留原视频所需署名和许可。</p><script>const v=document.getElementById('v');document.querySelectorAll('[data-t]').forEach(b=>b.onclick=()=>{v.currentTime=Number(b.dataset.t);v.play().catch(()=>{});});</script></html>'''
    page=page.replace('<th>英文</th>','<th>说话人</th><th>英文</th>').replace('说话人身份未识别。','按整句已检测语音时长的多数判定说话人，边界冲突不阻止归属；无语音或无多数时保留未知。编号只在本片内有效，不代表已核实身份。')
    artifact(job,'review.html').write_text(page,encoding='utf-8')
    if table.get('diarization'):write_json(artifact(job,'speaker-turns.json'),table['diarization'])
    return {'status':state['status']}


def _logged(name,fn):
    def node(state):
        event(state['job_dir'],name,'started');started=time.perf_counter()
        try:
            result=fn(state);event(state['job_dir'],name,'completed',elapsed_sec=time.perf_counter()-started);return result
        except Exception as exc:
            event(state['job_dir'],name,'failed',code=getattr(exc,'code','NODE_FAILED'),error_type=type(exc).__name__);raise
    return node


def build_sentence_graph(checkpointer=None,interrupt_after=None):
    from .audio_recheck import recheck_node
    from .diarization import diarization_node
    graph=StateGraph(SentenceState)
    nodes=[('resolve_input',_resolve),('download_video',_acquire),('prepare_full_audio',_prepare),
           ('asr_and_sentence_formation',_recognize_sentence),('recheck_incomplete_audio',recheck_node),('diarize_speakers',diarization_node),('review_sentences',_review),('export_sentences',_export)]
    for name,fn in nodes:graph.add_node(name,_logged(name,fn))
    graph.add_edge(START,nodes[0][0])
    for a,b in zip(nodes,nodes[1:]):graph.add_edge(a[0],b[0])
    graph.add_edge(nodes[-1][0],END)
    return graph.compile(checkpointer=checkpointer,interrupt_after=interrupt_after,name='B_complete_video_sentence_timeline_v2')


def _execute(job,initial=None,stop_after=None):
    job=Path(job).resolve();request=read_json(job/'request.json')
    if fingerprint(request['model_dir'])!=request['runtime']:raise BError('RUNTIME_CHANGED','Use a new job after code/model/environment changes')
    if request.get('diarization',{}).get('enabled'):
        from .diarization import model_files
        config=request['diarization']
        if {name:digest(p) for name,p in model_files(config['model_dir']).items()}!=config['model_sha256'] or importlib.metadata.version('sherpa-onnx')!=config['version']:
            raise BError('DIARIZATION_RUNTIME_CHANGED','Diarization model/environment changed')
    from .workflow import job_lock
    with job_lock(job),SqliteSaver.from_conn_string(str(job/'checkpoints.sqlite')) as saver:
        graph=build_sentence_graph(saver,[stop_after] if stop_after else None);config={'configurable':{'thread_id':job.name}}
        if initial is None:
            old=graph.get_state(config).values
            if not old:raise BError('NO_CHECKPOINT','No checkpoint to resume')
            if old.get('media_ref') and digest(artifact(job,old['media_ref']))!=old['source_meta']['sha256']:
                raise BError('ARTIFACT_CHANGED','Source video changed')
            if old.get('audio_ref') and digest(artifact(job,old['audio_ref']))!=read_json(artifact(job,'media.json'))['audio_sha256']:
                raise BError('ARTIFACT_CHANGED','Prepared audio changed')
        try:
            for update in graph.stream(initial,config,stream_mode='updates'):
                for name in update:
                    if name!='__interrupt__':print('[LangGraph V2]',name,flush=True)
            snapshot=graph.get_state(config);state=snapshot.values
            status='paused' if snapshot.next else state.get('status','unknown')
            write_json(job/'run-status.json',{'status':status,'next_nodes':list(snapshot.next),'pipeline_version':'sentence-v2',
                       'human_confirmed':False,'original_asr_timestamps_persisted':False})
            return {**state,'job_status':status,'next_nodes':list(snapshot.next)}
        except Exception as exc:
            write_json(job/'run-status.json',{'status':'failed','code':getattr(exc,'code','NODE_FAILED'),
                       'original_asr_timestamps_persisted':False});raise


def run_sentences(input_ref,registry_path=None,model_dir=None,job_dir=None,*,allow_network=False,
                  max_duration_sec=7200,max_source_bytes=2*1024**3,download_timeout_sec=600,
                  node_path=None,audio_stream=None,video_stream=None,stop_after=None,
                  semantic_provider='none',allow_semantic_network=False,semantic_max_calls=1,
                  diarization=False,diarization_model_dir=None,num_speakers=None):
    if not 0<max_duration_sec<=7200:raise BError('DURATION_LIMIT','Maximum input is 7200 seconds')
    if max_source_bytes<=0 or max_source_bytes>8*1024**3:raise BError('SOURCE_SIZE','Source size limit must be in (0,8GiB]')
    if not 0<download_timeout_sec<=1800:raise BError('DOWNLOAD_TIMEOUT','Download timeout must be in (0,1800] seconds')
    if registry_path is not None:raise BError('INPUT_API_CHANGED','V2 takes a video path or YouTube URL directly; no registry required')
    if semantic_provider not in ['none','deepseek']:raise BError('SEMANTIC_CONFIG','Supported semantic provider: none or deepseek')
    semantic_config={'provider':semantic_provider,'allow_network':bool(allow_semantic_network),'max_calls':semantic_max_calls}
    if semantic_provider=='deepseek':
        from .semantic_review import DeepSeekHTTP
        reviewer=DeepSeekHTTP(allow_network=allow_semantic_network,max_calls=semantic_max_calls)
        semantic_config.update({'model':reviewer.model,'base_url':reviewer.base_url})
    if model_dir is None:model_dir=ROOT/'models/faster-whisper-base.en'
    if job_dir is None:raise BError('JOB_REQUIRED','Provide a new job directory')
    resolve_input(input_ref)
    if node_path is None:
        candidate=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        node_path=candidate if Path(candidate).is_file() else None
    diarization_config={'enabled':bool(diarization)}
    if diarization:
        from .diarization import model_files,DEFAULT_MODEL_DIR
        if num_speakers is not None and (type(num_speakers) is not int or not 1<=num_speakers<=32):raise BError('SPEAKER_COUNT','num_speakers must be in [1,32]')
        folder=Path(diarization_model_dir or DEFAULT_MODEL_DIR).resolve()
        diarization_config.update({'model_dir':str(folder),'num_speakers':num_speakers,'threshold':.5,
             'model_sha256':{name:digest(p) for name,p in model_files(folder).items()},'version':importlib.metadata.version('sherpa-onnx')})
    runtime=fingerprint(model_dir);job=Path(job_dir).resolve();job.mkdir(parents=True,exist_ok=False)
    r={'pipeline_version':'sentence-v2','input_ref':str(input_ref),'model_dir':str(Path(model_dir).resolve()),
       'allow_network':bool(allow_network),'max_duration_sec':max_duration_sec,'max_source_bytes':max_source_bytes,
       'download_timeout_sec':download_timeout_sec,'node_path':node_path,'audio_stream':audio_stream,'video_stream':video_stream,
       'runtime':runtime,'external_audio_chunks':False,'original_asr_timestamps_persisted':False,
       'semantic_review':semantic_config,'diarization':diarization_config}
    write_json(job/'request.json',r)
    return _execute(job,{'job_dir':str(job),'request':r},stop_after)


def resume_sentences(job_dir):
    if read_json(Path(job_dir)/'request.json').get('pipeline_version')!='sentence-v2':
        from .workflow import resume_b
        return resume_b(job_dir)
    return _execute(job_dir)


def load_sentence_table(path):
    table=read_json(path)
    if table.get('schema_version')!='b-sentences-2':
        from .workflow import load_timetable
        return load_timetable(path)
    errors=validate_sentence_table(table)
    if errors:raise BError('TIMETABLE_INVALID','; '.join(errors))
    return table
