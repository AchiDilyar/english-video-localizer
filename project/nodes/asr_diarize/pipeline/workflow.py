from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import importlib.metadata
import math
import os
from pathlib import Path
import time
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from nodes.probe_input import media as b_media
from .common import BError, artifact, digest, event, object_hash, read_json, write_json
from .sources import acquire, select_source
from .grouping import make_groups
from .exporting import build_timetable, export, validate_timetable

ROOT=Path(__file__).resolve().parents[4]
NODES=['resolve_source','acquire_media','prepare_audio','transcribe','group_sentences','validate_timetable','export_timetable','needs_review']


def merge_dict(old,new):return {**old,**new}


class BState(TypedDict,total=False):
    job_dir:str
    request:dict
    source:dict
    media_ref:str
    media_sha256:str
    audio_ref:str
    media_report_ref:str
    asr_ref:str
    asr_meta_ref:str
    groups_ref:str
    draft_ref:str
    timetable_ref:str
    validation_errors:list[str]
    status:str
    artifact_hashes:Annotated[dict,merge_dict]


def runtime_fingerprint(model_dir):
    model=Path(model_dir)
    names=['model.bin','config.json','tokenizer.json','vocabulary.txt']
    if any(not (model/n).is_file() for n in names):raise BError('MODEL_UNAVAILABLE','Required local English model files are missing')
    return {'model_files':{n:digest(model/n) for n in names},
            'model_download':read_json(model/'download-provenance.json') if (model/'download-provenance.json').is_file() else None,
            'code':{str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'project/nodes/asr_diarize/pipeline').glob('*.py'))},
            'tools':{n:digest((ROOT/'project/nodes/probe_input/media.py' if n=='b_media.py' else ROOT/'project/nodes/asr_diarize/pipeline/group_sample_sentences.py')) for n in ['b_media.py','group_sample_sentences.py']},
            'binaries':{n:digest(b_media.tool_path(n)) for n in ['ffmpeg','ffprobe']},
            'packages':{n:importlib.metadata.version(n) for n in ['langgraph','langgraph-checkpoint-sqlite','faster-whisper','ctranslate2','av','numpy']}}


def cached_node(name, function):
    def wrapped(state):
        job=state['job_dir'];request=state['request'];cache=artifact(job,f'node-cache/{name}.json')
        signature=object_hash(request)
        started=time.perf_counter();event(job,name,'started')
        try:
            if cache.is_file():
                old=read_json(cache)
                if old['request_hash']!=signature:raise BError('CACHE_CONFIG_CHANGED','Cached node configuration differs')
                for ref,expected in old['result'].get('artifact_hashes',{}).items():
                    if not artifact(job,ref).is_file() or digest(artifact(job,ref))!=expected:
                        raise BError('ARTIFACT_CHANGED',f'Cached artifact changed: {ref}')
                result=old['result'];reused=True
            else:
                result,refs=function(state)
                result['artifact_hashes']={ref:digest(artifact(job,ref)) for ref in refs}
                write_json(cache,{'request_hash':signature,'result':result})
                reused=False
            event(job,name,'completed',elapsed_sec=time.perf_counter()-started,reused=reused)
            return result
        except Exception as exc:
            paused=getattr(exc,'code',None) in ['DOWNLOAD_PAUSED','ASR_CHUNKS_PAUSED']
            event(job,name,'paused' if paused else 'failed',error_type=type(exc).__name__,code=getattr(exc,'code','NODE_FAILED'))
            raise
    wrapped.__name__=name
    return wrapped


def resolve_node(state):
    job=state['job_dir'];r=state['request']
    source=select_source(r['input_ref'],artifact(job,'inputs/registry.json'))
    if source['kind']=='local':
        p=Path(source['local_path'])
        if not p.is_file():raise BError('INPUT_NOT_FOUND','Registered local source is missing')
        actual=digest(p)
        if source.get('expected_sha256') and source['expected_sha256']!=actual:raise BError('HASH_MISMATCH','Local source differs from registry')
        source['expected_sha256']=actual
    write_json(artifact(job,'source.json'),source)
    return {'source':source},['source.json']


def acquire_node(state):
    job=state['job_dir'];result=acquire(state['source'],job,state['request']['allow_network'],state['request'])
    write_json(artifact(job,'acquisition.json'),result)
    refs=[result['media_ref'],'acquisition.json']
    if state['source']['kind']=='https_file':refs.append('source/video.mp4.download.json')
    return {k:result[k] for k in ['media_ref','media_sha256']},refs


def audio_node(state):
    job=state['job_dir'];r=state['request'];video=artifact(job,state['media_ref'])
    info=b_media.inspect(video,b_media.tool_path('ffprobe'),r['audio_stream'],r['video_stream'])
    if not info['duration_ms'] or info['duration_ms']>r['max_duration_sec']*1000+100:
        raise BError('DURATION_LIMIT','Media duration exceeds configured limit or is unknown')
    b_media.extract(video,artifact(job,'audio'),b_media.tool_path('ffprobe'),b_media.tool_path('ffmpeg'),
                    r['audio_stream'],r['video_stream'],r.get('prepare_timeout_sec',120))
    return {'audio_ref':'audio/audio.wav','media_report_ref':'audio/media-report.json'},['audio/audio.wav','audio/media-report.json']


def asr_node(state):
    from faster_whisper import WhisperModel
    job=state['job_dir'];r=state['request'];started=time.perf_counter()
    factory=lambda:WhisperModel(r['model_dir'],device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    chunk_refs=[];extra={}
    if r.get('chunk_seconds'):
        from .chunking import transcribe_chunks
        raw,extra,chunk_refs=transcribe_chunks(job,artifact(job,state['audio_ref']),r,factory)
        load=extra['load_sec_this_invocation'];elapsed=extra['inference_sec']
    else:
        model=factory();load=time.perf_counter()-started;start=time.perf_counter()
        segments,info=model.transcribe(str(artifact(job,state['audio_ref'])),language='en',beam_size=5,
                                       temperature=0,word_timestamps=True,vad_filter=False,condition_on_previous_text=True)
        raw={'info':asdict(info),'segments':[asdict(s) for s in segments]}
        elapsed=time.perf_counter()-start
    if not raw['segments']:raise BError('NO_SPEECH','No speech was recognized')
    if artifact(job,'asr/raw.json').exists():raise BError('RAW_EXISTS','Refusing to overwrite raw ASR predictions')
    write_json(artifact(job,'asr/raw.json'),raw)
    meta={'engine':'faster-whisper','model_dir':r['model_dir'],'runtime':r['runtime'],
          'device':'cpu','compute_type':'int8','cpu_threads':4,'language':'en','beam_size':5,
          'temperature':0,'word_timestamps':True,'vad_filter':False,'condition_on_previous_text':True,
          'speaker_mode':r['speaker_mode'],'diarization_executed':False,
          'load_sec':load,'inference_sec':elapsed,'audio_sha256':digest(artifact(job,state['audio_ref'])),
          'segment_count':len(raw['segments']),'word_count':sum(len(s['words'] or []) for s in raw['segments']),
          'paid_api_calls':0,'deepseek_used':False,'chunked':bool(r.get('chunk_seconds')),**extra}
    write_json(artifact(job,'asr/execution.json'),meta)
    return {'asr_ref':'asr/raw.json','asr_meta_ref':'asr/execution.json'},['asr/raw.json','asr/execution.json',*chunk_refs]


def grouping_node(state):
    job=state['job_dir'];path=artifact(job,state['asr_ref']);data=path.read_bytes();raw=read_json(path)
    result=make_groups(raw,data,digest(artifact(job,state['audio_ref'])),digest(path),
                       state['request']['speaker_mode'],state['request']['group_reference'])
    write_json(artifact(job,'groups.json'),result)
    return {'groups_ref':'groups.json'},['groups.json']


def validate_node(state):
    job=state['job_dir']
    bundle=build_timetable(read_json(artifact(job,state['asr_ref'])),read_json(artifact(job,state['groups_ref'])),
                           state['source'],read_json(artifact(job,state['media_report_ref'])),
                           read_json(artifact(job,state['asr_meta_ref'])))
    errors=validate_timetable(bundle)
    write_json(artifact(job,'draft-timetable.json'),bundle)
    write_json(artifact(job,'validation.json'),{'schema_and_trace_valid':not errors,'errors':errors,
               'human_accuracy_verified':False})
    return {'draft_ref':'draft-timetable.json','validation_errors':errors},['draft-timetable.json','validation.json']


def export_node(state):
    job=state['job_dir'];bundle=read_json(artifact(job,state['draft_ref']))
    ref=export(job,bundle,state['media_ref'])
    return {'timetable_ref':ref,'status':'ready_for_human_review'},[ref,'segments.csv','sentence-groups.csv','words.csv','review.html']


def review_node(state):
    write_json(artifact(state['job_dir'],'review-required.json'),{'status':'blocked_validation','errors':state['validation_errors']})
    return {'status':'blocked_validation'},['review-required.json']


def build_b_graph(checkpointer=None,interrupt_after=None):
    """Return a compiled B-only subgraph, callable from F's parent workflow."""
    builder=StateGraph(BState)
    functions=[resolve_node,acquire_node,audio_node,asr_node,grouping_node,validate_node,export_node,review_node]
    for name,function in zip(NODES,functions):builder.add_node(name,cached_node(name,function))
    builder.add_edge(START,NODES[0])
    for a,b in zip(NODES[:5],NODES[1:6]):builder.add_edge(a,b)
    builder.add_conditional_edges('validate_timetable',lambda s:'bad' if s['validation_errors'] else 'ok',
                                  {'bad':'needs_review','ok':'export_timetable'})
    builder.add_edge('export_timetable',END);builder.add_edge('needs_review',END)
    return builder.compile(checkpointer=checkpointer,interrupt_after=interrupt_after,name='B_media_to_english_timetable')


def build_b_export_graph(checkpointer=None):
    """Revalidate/re-export verified existing predictions; never calls network or ASR."""
    builder=StateGraph(BState)
    for name,fn in [('validate_timetable',validate_node),('export_timetable',export_node),('needs_review',review_node)]:
        builder.add_node(name,cached_node(name,fn))
    builder.add_edge(START,'validate_timetable')
    builder.add_conditional_edges('validate_timetable',lambda s:'bad' if s['validation_errors'] else 'ok',
                                  {'bad':'needs_review','ok':'export_timetable'})
    builder.add_edge('export_timetable',END);builder.add_edge('needs_review',END)
    return builder.compile(checkpointer=checkpointer,name='B_revalidate_preserved_ASR')


@contextmanager
def job_lock(job):
    path=artifact(job,'.running.lock')
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError as exc:raise BError('JOB_BUSY','Job is already running or a stale lock needs manual inspection') from exc
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd);yield
    finally:path.unlink(missing_ok=True)


def _execute(job,initial=None,stop_after=None):
    job=Path(job).resolve();r=read_json(job/'request.json')
    if runtime_fingerprint(r['model_dir'])!=r['runtime']:
        raise BError('RUNTIME_CHANGED','Code, engine, FFmpeg or model changed; use a new job')
    for relative,expected in r['input_hashes'].items():
        if digest(artifact(job,relative))!=expected:raise BError('INPUT_CHANGED','Frozen registry/reference files changed')
    with job_lock(job),SqliteSaver.from_conn_string(str(job/'checkpoints.sqlite')) as saver:
        graph=(build_b_export_graph(saver) if r.get('operation')=='reexport' else
               build_b_graph(saver,[stop_after] if stop_after else None))
        config={'configurable':{'thread_id':job.name}}
        previous=graph.get_state(config)
        if initial is None and not previous.values:raise BError('NO_CHECKPOINT','Job has no resumable checkpoint')
        for ref,expected in previous.values.get('artifact_hashes',{}).items():
            if not artifact(job,ref).is_file() or digest(artifact(job,ref))!=expected:
                raise BError('ARTIFACT_CHANGED',f'Resume artifact changed or missing: {ref}')
        started=time.perf_counter();event(job,'workflow','started',resume=initial is None)
        try:
            for update in graph.stream(initial,config,stream_mode='updates'):
                for name in update:
                    if name!='__interrupt__':print(f'[LangGraph] {name}',flush=True)
            snapshot=graph.get_state(config);state=snapshot.values
            status='paused' if snapshot.next else state.get('status','unknown')
            write_json(job/'run-status.json',{'status':status,'next_nodes':list(snapshot.next),
                       'elapsed_sec_this_invocation':time.perf_counter()-started,
                       'timetable_ref':state.get('timetable_ref'),'job_dir':str(job),
                       'langgraph_executed':True,'resume':initial is None,
                       'human_accuracy_verified':False,'paid_api_calls':0})
            event(job,'workflow','paused' if snapshot.next else 'completed',next_nodes=list(snapshot.next))
            return {**state,'job_status':status,'next_nodes':list(snapshot.next)}
        except Exception as exc:
            code=getattr(exc,'code','NODE_FAILED')
            if code in ['DOWNLOAD_PAUSED','ASR_CHUNKS_PAUSED']:
                snapshot=graph.get_state(config);state=snapshot.values
                write_json(job/'run-status.json',{'status':'paused','code':code,'next_nodes':list(snapshot.next),
                           'elapsed_sec_this_invocation':time.perf_counter()-started,'langgraph_executed':True})
                event(job,'workflow','paused',code=code,next_nodes=list(snapshot.next))
                return {**state,'job_status':'paused','next_nodes':list(snapshot.next)}
            write_json(job/'run-status.json',{'status':'failed','error_type':type(exc).__name__,
                       'code':getattr(exc,'code','NODE_FAILED'),'elapsed_sec_this_invocation':time.perf_counter()-started})
            event(job,'workflow','failed',error_type=type(exc).__name__)
            raise


def run_b(input_ref,registry_path,model_dir,job_dir,*,allow_network=False,speaker_mode='single_assumed',
          group_plan=None,reference_asr=None,stop_after=None,max_duration_sec=120,audio_stream=None,video_stream=None,
          chunk_seconds=None,chunk_search_seconds=5,asr_chunks_per_invocation=None,
          asr_time_budget_sec=600,download_timeout_sec=180,max_source_bytes=256*1024*1024,
          prepare_timeout_sec=180,pause_download_once_bytes=None):
    """Run a new isolated job. Existing job directories are never overwritten."""
    if speaker_mode not in ['single_assumed','unknown']:raise BError('SPEAKER_MODE','Supported: single_assumed, unknown')
    if type(max_duration_sec) not in [int,float] or not math.isfinite(max_duration_sec) or not 0<max_duration_sec<=3600:
        raise BError('DURATION_LIMIT','Maximum duration must be in (0,3600] seconds')
    if chunk_seconds is None and max_duration_sec>120:chunk_seconds=120
    if chunk_seconds is not None and (type(chunk_seconds) not in [int,float] or not math.isfinite(chunk_seconds) or not 1<=chunk_seconds<=300):
        raise BError('CHUNK_CONFIG','Chunk target must be 1–300 seconds')
    if type(chunk_search_seconds) not in [int,float] or not math.isfinite(chunk_search_seconds) or not 0<=chunk_search_seconds<=10:
        raise BError('CHUNK_CONFIG','Silence search window must be 0–10 seconds')
    if asr_chunks_per_invocation is not None and (type(asr_chunks_per_invocation) is not int or asr_chunks_per_invocation<1):
        raise BError('CHUNK_CONFIG','ASR chunk batch must be a positive integer')
    for name,value in [('asr_time_budget_sec',asr_time_budget_sec),('download_timeout_sec',download_timeout_sec),('prepare_timeout_sec',prepare_timeout_sec)]:
        if type(value) not in [int,float] or not math.isfinite(value) or not 0<value<=600:raise BError('TIME_LIMIT',name+' must be in (0,600]')
    if type(max_source_bytes) is not int or not 0<max_source_bytes<=1024**3:raise BError('DOWNLOAD_LIMIT','Source limit must be in (0,1GiB]')
    if pause_download_once_bytes is not None and (type(pause_download_once_bytes) is not int or not 0<pause_download_once_bytes<=max_source_bytes):raise BError('DOWNLOAD_LIMIT','Invalid one-time pause point')
    if chunk_seconds and reference_asr:raise BError('GROUP_REFERENCE','Chunked ASR requires a new grouping plan; old short-clip plans cannot be reused')
    if stop_after and stop_after not in NODES:raise BError('STOP_NODE','Unknown node')
    if bool(group_plan)!=bool(reference_asr):raise BError('GROUP_REFERENCE','Provide both plan and reference ASR')
    # Freeze local registry paths before copying the registry into a job.
    registry=read_json(registry_path)
    for entry in registry.get('sources',[]):
        if entry.get('kind')=='local':entry['local_path']=str((Path(registry_path).resolve().parent/entry['local_path']).resolve())
    job=Path(job_dir).resolve();job.mkdir(parents=True,exist_ok=False)
    write_json(job/'inputs/registry.json',registry)
    reference=None
    if reference_asr:
        import shutil
        shutil.copyfile(reference_asr,job/'inputs/reference-asr.json')
        shutil.copyfile(group_plan,job/'inputs/reference-plan.json')
        old_meta=read_json(Path(reference_asr).parent/'execution.json')
        reference={'asr_path':str(job/'inputs/reference-asr.json'),'plan_path':str(job/'inputs/reference-plan.json'),
                   'audio_sha256':old_meta['audio_sha256']}
    request={'input_ref':str(input_ref),'model_dir':str(Path(model_dir).resolve()),'allow_network':bool(allow_network),
             'speaker_mode':speaker_mode,'max_duration_sec':max_duration_sec,'audio_stream':audio_stream,'video_stream':video_stream,
             'group_reference':reference,'runtime':runtime_fingerprint(model_dir),
             'chunk_seconds':chunk_seconds,'chunk_search_seconds':chunk_search_seconds,
             'asr_chunks_per_invocation':asr_chunks_per_invocation,'asr_time_budget_sec':asr_time_budget_sec,
             'download_timeout_sec':download_timeout_sec,'max_source_bytes':max_source_bytes,
             'prepare_timeout_sec':prepare_timeout_sec,'pause_download_once_bytes':pause_download_once_bytes,
             'input_hashes':{str(p.relative_to(job)):digest(p) for p in (job/'inputs').glob('*.json')}}
    write_json(job/'request.json',request)
    return _execute(job,{'job_dir':str(job),'request':request},stop_after)


def resume_b(job_dir):
    """Resume the same SQLite task, verifying all completed artifact hashes first."""
    return _execute(job_dir)


def reexport_b(source_job,job_dir):
    """Import hash-verified completed predictions into a NEW postprocessing job.

    Original job/checkpoints/raw bytes remain unchanged. This intentionally is not
    a way to claim old nodes ran with new code or to bypass runtime resume checks.
    """
    import shutil
    old=Path(source_job).resolve();job=Path(job_dir).resolve()
    values={};hashes={}
    for name in ['resolve_source','acquire_media','prepare_audio','transcribe','group_sentences']:
        cache=read_json(artifact(old,f'node-cache/{name}.json'))
        result=cache['result']
        for ref,expected in result['artifact_hashes'].items():
            if not artifact(old,ref).is_file() or digest(artifact(old,ref))!=expected:
                raise BError('IMPORT_ARTIFACT_CHANGED',f'Preserved source artifact changed: {ref}')
            hashes[ref]=expected
        values.update({k:v for k,v in result.items() if k!='artifact_hashes'})
    old_request=read_json(old/'request.json')
    job.mkdir(parents=True,exist_ok=False)
    for ref,expected in hashes.items():
        target=artifact(job,ref);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(artifact(old,ref),target)
        if digest(target)!=expected:raise BError('IMPORT_COPY_FAILED','Copied artifact hash differs')
    write_json(job/'inputs/imported-artifacts.json',{'source_job':str(old),'source_request_sha256':digest(old/'request.json'),
               'artifacts':hashes,'purpose':'Postprocess preserved predictions; zero new ASR/network calls'})
    shutil.copyfile(old/'request.json',job/'inputs/original-request.json')
    request={**old_request,'operation':'reexport','allow_network':False,'imported_from_job':str(old),
             'runtime':runtime_fingerprint(old_request['model_dir']),
             'input_hashes':{str(p.relative_to(job)):digest(p) for p in (job/'inputs').glob('*.json')}}
    write_json(job/'request.json',request)
    event(job,'import','completed',source_job=str(old),asr_calls=0,network_calls=0)
    return _execute(job,{'job_dir':str(job),'request':request,**values,'artifact_hashes':hashes})


def load_timetable(path):
    """Downstream C/D/E API: load and validate B's structured output."""
    result=read_json(path)
    try:errors=validate_timetable(result)
    except (KeyError,TypeError,ValueError) as exc:raise BError('TIMETABLE_INVALID','Missing or malformed timetable fields') from exc
    if errors:raise BError('TIMETABLE_INVALID','; '.join(errors))
    return result
