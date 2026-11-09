"""Offline neural speaker diarization and conservative sentence attribution."""
import copy
import importlib.metadata
from pathlib import Path
import time
import wave

import numpy as np
from .common import BError,digest,milliseconds

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR=ROOT/'models/diarization'


def model_files(model_dir=DEFAULT_MODEL_DIR):
    folder=Path(model_dir);paths={name:folder/name for name in ['segmentation.onnx','embedding.onnx']}
    if any(not p.is_file() for p in paths.values()):raise BError('DIARIZATION_MODEL_MISSING','Download local diarization models with tools.bootstrap_diarization first')
    return paths


def diarize(audio_path,model_dir=DEFAULT_MODEL_DIR,*,num_speakers=None,threshold=.5):
    import sherpa_onnx as so
    if num_speakers is not None and (type(num_speakers) is not int or not 1<=num_speakers<=32):
        raise BError('SPEAKER_COUNT','num_speakers must be None or an integer in [1,32]')
    if not 0<threshold<2:raise BError('SPEAKER_THRESHOLD','Clustering threshold must be in (0,2)')
    paths=model_files(model_dir);started=time.perf_counter()
    config=so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(paths['segmentation.onnx']),window_shift_ratio=.25),
            num_threads=4,provider='cpu'),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(paths['embedding.onnx']),num_threads=4,provider='cpu'),
        clustering=so.FastClusteringConfig(num_clusters=num_speakers if num_speakers is not None else -1,threshold=threshold),
        min_duration_on=.3,min_duration_off=.5)
    if not config.validate():raise BError('DIARIZATION_CONFIG','Invalid sherpa-onnx configuration')
    engine=so.OfflineSpeakerDiarization(config)
    with wave.open(str(audio_path),'rb') as wav:
        if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
            raise BError('DIARIZATION_AUDIO','Expected 16kHz mono PCM16 WAV')
        duration=wav.getnframes()/16000
        samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype=np.int16).astype(np.float32)/32768
    last=[-1]
    def progress(done,total):
        bucket=int(done/max(total,1)*10)
        if bucket!=last[0]:print(f'[diarization] {bucket*10}% segmentation',flush=True);last[0]=bucket
        return 0
    result=engine.process(samples,callback=progress).sort_by_start_time()
    mapping={};turns=[]
    for turn in result:
        begin=max(0,milliseconds(turn.start));end=min(milliseconds(duration),milliseconds(turn.end))
        if begin>=end:continue
        if turn.speaker not in mapping:mapping[turn.speaker]=f'speaker_{len(mapping)+1:03d}'
        turns.append({'start_ms':begin,'end_ms':end,'speaker_id':mapping[turn.speaker]})
    if not turns:raise BError('NO_SPEECH_SPEAKERS','No reliable speaker turns detected')
    return {'turns':turns,'speaker_ids':list(mapping.values()),'metadata':{
        'engine':'sherpa-onnx','version':importlib.metadata.version('sherpa-onnx'),
        'segmentation_model':'pyannote-segmentation-3.0 ONNX','embedding_model':'wespeaker_en_voxceleb_resnet34 ONNX',
        'model_sha256':{name:digest(path) for name,path in paths.items()},'audio_sha256':digest(audio_path),
        'duration_ms':milliseconds(duration),'elapsed_sec':time.perf_counter()-started,
        'num_speakers_requested':num_speakers,'num_speakers_detected':len(mapping),'clustering_threshold':threshold,
        'window_shift_ratio':.25,'device':'cpu','threads':4,'human_confirmed':False,
        'speaker_ids_scope':'within_this_video_only; ordered_by_first_detected_occurrence',
        'identity_names_inferred':False,'audio_uploaded':False,'speaker_embeddings_persisted':False}}


def _union_length(intervals):
    end=-1;total=0
    for a,b in sorted(intervals):
        total+=max(0,b-max(a,end));end=max(end,b)
    return total


def assign_speakers(table,result):
    """Assign the speaker with >50% of detected speaker-time; ignore boundary conflicts."""
    out=copy.deepcopy(table);assigned=0;unresolved=0
    for row in out['sentences']:
        intervals={}
        for turn in result['turns']:
            a=max(row['start_ms'],turn['start_ms']);b=min(row['end_ms'],turn['end_ms'])
            if b>a:intervals.setdefault(turn['speaker_id'],[]).append((a,b))
        durations=sorted(((sid,_union_length(parts)) for sid,parts in intervals.items()),key=lambda x:(-x[1],x[0]))
        total=sum(d for _,d in durations);duration=row['end_ms']-row['start_ms']
        share=durations[0][1]/total if total else 0
        coverage=durations[0][1]/duration if durations else 0
        reliable=bool(durations) and durations[0][1]*2>total
        tied=len(durations)>1 and durations[0][1]==durations[1][1]
        row['speaker_id']=durations[0][0] if reliable else None
        row['speaker_assignment']={'method':'whole_sentence_speaker_time_majority_v3','decision':'majority_speaker' if reliable else ('no_speech' if not durations else ('duration_tie' if tied else 'no_majority')),'top_active_speech_share':round(share,4),
                                  'top_sentence_time_coverage':round(coverage,4),'human_confirmed':False,
                                  'candidate_speaker_ids':[sid for sid,_ in durations]}
        row['review_issues']=[x for x in row['review_issues'] if x not in ['speaker_unresolved','multiple_speakers_in_sentence','speaker_boundary_overlap','speaker_duration_tie','speaker_no_majority']]
        if reliable:assigned+=1
        else:
            unresolved+=1;row['review_issues'].append('speaker_unresolved' if not durations else ('speaker_duration_tie' if tied else 'speaker_no_majority'))
        row['review_status']='needs_human_review' if row['review_issues'] else 'automatic_checks_passed'
    out['diarization']=result
    out['verification']['automatic_diarization_executed']=True
    out['verification']['speaker_labels_human_verified']=False
    out['review']['speaker_assignment']={'assigned_sentences':assigned,'unresolved_sentences':unresolved,
        'policy':'assign >50% of detected speaker-time across whole sentence; ignore boundary conflicts; no speech/tie/no majority stays null',
        'policy_version':3,'majority_threshold_exclusive':.5}
    return out


def diarization_node(state):
    from .common import artifact
    config=state['request'].get('diarization',{'enabled':False})
    if not config.get('enabled'):return {'table':state['table']}
    result=diarize(artifact(state['job_dir'],state['audio_ref']),config['model_dir'],
                   num_speakers=config.get('num_speakers'),threshold=config.get('threshold',.5))
    return {'table':assign_speakers(state['table'],result)}
