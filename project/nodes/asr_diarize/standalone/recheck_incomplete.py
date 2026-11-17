"""New LangGraph repair task reusing completed full-video outputs; source is immutable."""
import argparse
import shutil
from pathlib import Path
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.sqlite import SqliteSaver
from nodes.asr_diarize.pipeline.common import read_json,write_json,digest
from nodes.asr_diarize.pipeline.sentence_mode import SentenceState,_review,_export,_logged,fingerprint
from nodes.asr_diarize.pipeline.audio_recheck import recheck_node


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-job',required=True);p.add_argument('--job-dir',required=True)
    p.add_argument('--sentence-id',action='append');a=p.parse_args()
    source=Path(a.source_job).resolve();job=Path(a.job_dir).resolve()
    table=read_json(source/'timetable.json');media=read_json(source/'media.json');request=read_json(source/'request.json')
    video=next((source/'source').glob('video.*'))
    if digest(source/'audio.wav')!=media['audio_sha256'] or digest(video)!=media['video_sha256']:raise ValueError('Source artifacts changed')
    job.mkdir(parents=True,exist_ok=False);(job/'source').mkdir()
    shutil.copy2(video,job/'source'/video.name);shutil.copy2(source/'audio.wav',job/'audio.wav')
    shutil.copy2(source/'media.json',job/'media.json')
    request.update({'pipeline_version':'audio-recheck-v1','parent_job':str(source),'runtime':fingerprint(request['model_dir']),
                    'recheck_sentence_ids':a.sentence_id})
    write_json(job/'request.json',request)
    graph=StateGraph(SentenceState)
    for name,fn in [('local_audio_recheck',recheck_node),('review_sentences',_review),('export_sentences',_export)]:graph.add_node(name,_logged(name,fn))
    graph.add_edge(START,'local_audio_recheck');graph.add_edge('local_audio_recheck','review_sentences');graph.add_edge('review_sentences','export_sentences');graph.add_edge('export_sentences',END)
    initial={'job_dir':str(job),'request':request,'table':table,'media_ref':'source/'+video.name,'audio_ref':'audio.wav','duration_ms':table['duration_ms']}
    with SqliteSaver.from_conn_string(str(job/'checkpoints.sqlite')) as saver:
        result=graph.compile(checkpointer=saver).invoke(initial,{'configurable':{'thread_id':job.name}})
    report=result['table']['review']['audio_recheck'];write_json(job/'audio-recheck.json',report)
    write_json(job/'run-status.json',{'status':result['status'],'human_confirmed':False,'original_asr_timestamps_persisted':False})
    print({'status':result['status'],'checked':report['checked'],'provisional_repairs':report['provisional_repairs']})


if __name__=='__main__':main()
