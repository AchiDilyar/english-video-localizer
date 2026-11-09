"""Attach real local speaker labels to an existing final table in a new LangGraph job."""
import argparse
import importlib.metadata
import shutil
from pathlib import Path
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.sqlite import SqliteSaver
from b_pipeline.common import read_json,write_json,digest
from b_pipeline.sentence_mode import SentenceState,_review,_export,_logged,fingerprint
from b_pipeline.diarization import diarization_node,assign_speakers,model_files,DEFAULT_MODEL_DIR


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-job',required=True);p.add_argument('--job-dir',required=True)
    p.add_argument('--model-dir',default=str(DEFAULT_MODEL_DIR));p.add_argument('--num-speakers',type=int)
    p.add_argument('--reuse-turns',action='store_true',help='Reassign existing verified speaker turns without running models again')
    p.add_argument('--speaker-result',type=Path,help='Import local model result matching the source audio hash');a=p.parse_args()
    if a.speaker_result and (a.reuse_turns or a.num_speakers is not None):raise ValueError('External result cannot be combined with reuse or new speaker count')
    if a.reuse_turns and a.num_speakers is not None:raise ValueError('Cannot change speaker count while reusing turns')
    if a.num_speakers is not None and not 1<=a.num_speakers<=32:raise ValueError('Speaker count out of range')
    cached=a.reuse_turns or bool(a.speaker_result)
    source=Path(a.source_job).resolve();job=Path(a.job_dir).resolve();paths=model_files(a.model_dir) if not cached else {}
    table=read_json(source/'timetable.json');media=read_json(source/'media.json');request=read_json(source/'request.json')
    video=next((source/'source').glob('video.*'))
    if digest(source/'audio.wav')!=media['audio_sha256'] or digest(video)!=media['video_sha256']:raise ValueError('Source artifacts changed')
    if a.reuse_turns and (not table.get('diarization') or table['diarization']['metadata']['audio_sha256']!=media['audio_sha256']):raise ValueError('Cached speaker turns do not match audio')
    imported=read_json(a.speaker_result) if a.speaker_result else None
    if imported and (imported['metadata']['audio_sha256']!=media['audio_sha256'] or imported['metadata']['duration_ms']!=table['duration_ms']):raise ValueError('External speaker result does not match source audio')
    job.mkdir(parents=True,exist_ok=False);(job/'source').mkdir()
    shutil.copy2(video,job/'source'/video.name);shutil.copy2(source/'audio.wav',job/'audio.wav');shutil.copy2(source/'media.json',job/'media.json')
    request.update({'pipeline_version':'speaker-attribution-v2' if cached else 'diarization-v1','parent_job':str(source),'runtime':fingerprint(request['model_dir']),
                    'reuse_existing_speaker_turns':a.reuse_turns})
    if imported:
        request['imported_speaker_result_sha256']=digest(a.speaker_result)
        request['diarization']={'enabled':True,'provider':imported['metadata']['engine'],'result_imported':True}
        shutil.copy2(a.speaker_result,job/'imported-speaker-result.json')
    elif not a.reuse_turns:
        request['diarization']={'enabled':True,'model_dir':str(Path(a.model_dir).resolve()),'num_speakers':a.num_speakers,'threshold':.5,
                      'model_sha256':{name:digest(path) for name,path in paths.items()},'version':importlib.metadata.version('sherpa-onnx')}
    write_json(job/'request.json',request)
    graph=StateGraph(SentenceState)
    node_name='reassign_speakers' if cached else 'diarize_speakers'
    fn=(lambda state:{'table':assign_speakers(state['table'],imported or state['table']['diarization'])}) if cached else diarization_node
    for name,handler in [(node_name,fn),('review_sentences',_review),('export_sentences',_export)]:graph.add_node(name,_logged(name,handler))
    graph.add_edge(START,node_name);graph.add_edge(node_name,'review_sentences');graph.add_edge('review_sentences','export_sentences');graph.add_edge('export_sentences',END)
    initial={'job_dir':str(job),'request':request,'table':table,'media_ref':'source/'+video.name,'audio_ref':'audio.wav','duration_ms':table['duration_ms']}
    with SqliteSaver.from_conn_string(str(job/'checkpoints.sqlite')) as saver:result=graph.compile(checkpointer=saver).invoke(initial,{'configurable':{'thread_id':job.name}})
    write_json(job/'run-status.json',{'status':result['status'],'human_confirmed':False,'original_asr_timestamps_persisted':False})
    print(result['table']['review']['speaker_assignment'])


if __name__=='__main__':main()
