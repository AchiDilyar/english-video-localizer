"""Conservative proposal grouping and explicitly checked reference-plan replay."""
from pathlib import Path
import re

from tools.group_sample_sentences import group_bundle
from .common import BError, object_hash, read_json


def prediction_signature(raw):
    return object_hash([{'id':s['id'],'start':s['start'],'end':s['end'],'text':s['text'],
                         'words':[{k:w[k] for k in ['word','start','end']} for w in s.get('words') or []]}
                        for s in raw['segments']])


def make_groups(raw, raw_bytes, audio_sha256, source_sha256, speaker_mode, reference=None):
    speaker='SPEAKER_00' if speaker_mode=='single_assumed' else None
    method='single_speaker_assumption' if speaker else 'unknown'
    if reference:
        if audio_sha256!=reference['audio_sha256']:
            raise BError('GROUP_REFERENCE_MISMATCH','Reference grouping audio differs; do not apply old IDs to new speech')
        previous=read_json(reference['asr_path'])
        if prediction_signature(raw)!=prediction_signature(previous):
            raise BError('GROUP_REFERENCE_MISMATCH','Current words/times differ from reference; use fresh grouping and review')
        plan=read_json(reference['plan_path'])
        from .common import digest
        if digest(reference['asr_path'])!=plan['source_asr_sha256']:
            raise BError('GROUP_REFERENCE_MISMATCH','Reference plan is not bound to its reference ASR')
        plan={**plan,'source_asr_sha256':source_sha256,'speaker_id':speaker,'speaker_method':method}
        bundle=group_bundle(raw,plan,raw_bytes)
        bundle['grouping_method']='reference_plan_replayed_after_exact_words_and_times_match'
        return bundle
    proposals=[];current=[]
    for s in raw['segments']:
        if current:
            previous=current[-1]
            gap=s['start']-previous['end']
            unfinished=not re.search(r'[.!?][\"\u201d\u2019\x27]*$',previous['text'].strip())
            continuation=bool(re.match(r'\s*(you can|which|who|along with|just to)\b',s['text'],re.I))
            span=s['end']-current[0]['start']
            count=sum(len(x['text'].split()) for x in current)+len(s['text'].split())
            merge=(speaker is not None and 0<=gap<=.8 and span<=12 and count<=50
                   and (unfinished or continuation))
            if not merge:
                proposals.append(current);current=[]
        current.append(s)
    if current:proposals.append(current)
    plan={'source_asr_sha256':source_sha256,'speaker_id':speaker,'speaker_method':method,
          'groups':[{'source_segment_ids':[s['id'] for s in group],
                     'reason':'Conservative punctuation/pause/length heuristic; requires semantic review.'}
                    for group in proposals]}
    if plan['groups']:
        plan['groups'][0]['boundary_note']='clip_start_may_be_partial'
        plan['groups'][-1]['boundary_note']='clip_end_may_be_partial'
    bundle=group_bundle(raw,plan,raw_bytes)
    bundle['grouping_method']='heuristic_v1_gap_0.8_span_12_words_50'
    return bundle
