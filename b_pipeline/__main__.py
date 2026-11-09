import argparse
import json
import os
from pathlib import Path
import sys

os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'

from .sentence_mode import run_sentences,resume_sentences
from .video_inputs import download_input


def main():
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='V2: complete local/YouTube video to reviewed sentence-only timestamps, up to 2 hours; no external audio chunks')
    sub=p.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--input',required=True)
    run.add_argument('--model-dir',type=Path);run.add_argument('--job-dir',type=Path,required=True)
    run.add_argument('--allow-network',action='store_true');run.add_argument('--max-duration-sec',type=float,default=7200)
    run.add_argument('--max-source-mib',type=int,default=2048);run.add_argument('--download-timeout-sec',type=float,default=600)
    run.add_argument('--node-path');run.add_argument('--audio-stream',type=int);run.add_argument('--video-stream',type=int)
    run.add_argument('--semantic-provider',choices=['none','deepseek'],default='none')
    run.add_argument('--allow-semantic-network',action='store_true')
    run.add_argument('--semantic-max-calls',type=int,default=1)
    run.add_argument('--diarize',action='store_true',help='Run local neural speaker diarization')
    run.add_argument('--diarization-model-dir',type=Path)
    run.add_argument('--num-speakers',type=int,help='Optional known speaker count; default infer automatically')
    run.add_argument('--stop-after',choices=['resolve_input','download_video','prepare_full_audio','asr_and_sentence_formation','review_sentences'])
    resume=sub.add_parser('resume');resume.add_argument('--job-dir',type=Path,required=True)
    download=sub.add_parser('download');download.add_argument('--input',required=True);download.add_argument('--output-dir',type=Path,required=True)
    download.add_argument('--allow-network',action='store_true');download.add_argument('--max-source-mib',type=int,default=2048)
    download.add_argument('--download-timeout-sec',type=float,default=600);download.add_argument('--node-path')
    args=p.parse_args()
    try:
        if args.command=='download':
            node=args.node_path
            if node is None:
                candidate=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
                node=str(candidate) if candidate.is_file() else None
            path,meta=download_input(args.input,args.output_dir,allow_network=args.allow_network,
                max_bytes=args.max_source_mib*1024**2,download_timeout_sec=args.download_timeout_sec,node_path=node)
            print(json.dumps({**meta,'file':str(path)},ensure_ascii=False,indent=2));return 0
        if args.command=='resume':result=resume_sentences(args.job_dir)
        else:result=run_sentences(args.input,model_dir=args.model_dir,job_dir=args.job_dir,allow_network=args.allow_network,
                         max_duration_sec=args.max_duration_sec,max_source_bytes=args.max_source_mib*1024**2,
                         download_timeout_sec=args.download_timeout_sec,node_path=args.node_path,
                         audio_stream=args.audio_stream,video_stream=args.video_stream,stop_after=args.stop_after,
                         semantic_provider=args.semantic_provider,allow_semantic_network=args.allow_semantic_network,
                         semantic_max_calls=args.semantic_max_calls,diarization=args.diarize,
                         diarization_model_dir=args.diarization_model_dir,num_speakers=args.num_speakers)
        print(json.dumps({'job_dir':result['job_dir'],'job_status':result['job_status'],'next_nodes':result['next_nodes'],
                           'sentence_count':len(result.get('table',{}).get('sentences',[]))},ensure_ascii=False,indent=2))
        return 0 if result['job_status'] in ['ready_for_human_review','paused'] else 5
    except Exception as exc:
        print(json.dumps({'ok':False,'code':getattr(exc,'code','PIPELINE_FAILED'),'message':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 3


if __name__=='__main__':raise SystemExit(main())
