"""Audit completed V2 output and decoded SQLite checkpoint payloads, without ASR."""
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
import re

from langgraph.checkpoint.sqlite import SqliteSaver
from nodes.asr_diarize.pipeline.sentence_rules import validate_sentence_table


def main():
    parser=argparse.ArgumentParser();parser.add_argument('job');args=parser.parse_args()
    job=Path(args.job).resolve()
    if not job.resolve().is_relative_to((ROOT/'tests/tmp').resolve()):raise ValueError('Copy the task into tests/tmp before auditing')
    table=json.loads((job/'timetable.json').read_text(encoding='utf-8'))
    errors=validate_sentence_table(table)
    forbidden={'words','segments','original_segments','sentence_groups','raw_segments','raw_words'}
    def inspect(value):
        if isinstance(value,dict):
            assert not forbidden.intersection(value), 'Native ASR structure found'
            for item in value.values():inspect(item)
        elif isinstance(value,(tuple,list)):
            for item in value:inspect(item)
    inspect(table)
    for path in job.rglob('*.json'):inspect(json.loads(path.read_text(encoding='utf-8')))
    checkpoint_count=0
    with SqliteSaver.from_conn_string(str(job/'checkpoints.sqlite')) as saver:
        for checkpoint in saver.list({'configurable':{'thread_id':job.name}}):
            inspect(checkpoint.checkpoint);inspect(checkpoint.pending_writes);checkpoint_count+=1
    assert checkpoint_count>0
    assert not errors, errors
    execution=table['execution'];assert execution.get('full_video_transcribe_calls',execution['transcribe_calls'])==1
    assert execution['transcribe_calls']==execution.get('full_video_transcribe_calls',1)+execution.get('local_recheck_transcribe_calls',0)
    assert execution['external_audio_chunks']==0 and execution['raw_asr_timestamps_persisted'] is False
    assert not any(p.is_dir() and p.name in {'chunks','asr'} for p in job.rglob('*'))
    page=(job/'review.html').read_text(encoding='utf-8')
    src=re.search(r'<video[^>]*src="([^"]+)"',page).group(1)
    assert (job/src).is_file()
    (job/'review-script.js').write_text(re.search(r'<script>(.*?)</script>',page,re.S).group(1),encoding='utf-8')
    summary={'duration_ms':table['duration_ms'],'sentence_count':len(table['sentences']),
             'human_review_count':table['review']['sentences_needing_human_review'],
             'untimed_count':len(table['review']['untimed_utterances']),
             'automatic_repair_count':len(table['review']['automatic_repairs']),
             'structural_errors':errors,'decoded_checkpoints_checked':checkpoint_count,
             'native_asr_structure_found':False,'execution':execution}
    (job/'verification.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
