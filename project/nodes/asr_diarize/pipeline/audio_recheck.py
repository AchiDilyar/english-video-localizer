"""Local audio-based review of suspicious final sentences. No raw alignment persisted."""
import copy
import difflib
import logging
import re
import time
import wave

import numpy as np

logger=logging.getLogger(__name__)

from .sentence_rules import sentences_from_words,validate_sentence_table


def lexical(text):return re.findall(r"[\w']+",text.lower())


def insertion_only(old,new):
    a,b=lexical(old),lexical(new)
    changes=difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes()
    return bool(a) and len(b)>len(a) and len(b)-len(a)<=max(12,len(a)//2) and all(op in ['equal','insert'] for op,*_ in changes)


def recheck_table(table,audio_path,model,nlp,only_sentence_ids=None,*,strict_errors=False,subtitle_options=None):
    started=time.perf_counter();out=copy.deepcopy(table);original=table['sentences'];rows=[];records=[];calls=0;applied=0
    pending=copy.deepcopy(table['review'].get('untimed_utterances',[]))
    with wave.open(str(audio_path),'rb') as audio:
        if (audio.getframerate(),audio.getnchannels(),audio.getsampwidth())!=(16000,1,2):raise ValueError('Expected mono PCM16 16kHz WAV')
        for i,row in enumerate(original):
            if only_sentence_ids is not None and row['sentence_id'] not in only_sentence_ids:rows.append(copy.deepcopy(row));continue
            if not any(issue.startswith('possible_') for issue in row['review_issues']):rows.append(copy.deepcopy(row));continue
            # Neighboring text is heard as context, but only the target time interval may change.
            core_start=original[i-1]['end_ms'] if i else 0
            core_end=original[i+1]['start_ms'] if i+1<len(original) else table['duration_ms']
            start=max(0,(original[i-1]['start_ms'] if i else core_start)-1000)
            end=min(table['duration_ms'],(original[i+1]['end_ms'] if i+1<len(original) else core_end)+1000)
            record={'sentence_id':row['sentence_id'],'before':row['en'],'status':'unchanged','human_confirmed':False}
            if end-start>90000:
                record['status']='manual_review_window_too_long';records.append(record);rows.append(copy.deepcopy(row));continue
            audio.setpos(start*16)
            samples=np.frombuffer(audio.readframes((end-start)*16),dtype=np.int16).astype(np.float32)/32768
            hypotheses=[]
            try:
                for beam in [5,1]:
                    calls+=1
                    segments,_=model.transcribe(samples,language='en',beam_size=beam,temperature=0,
                        word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
                    aligned=[]
                    for segment in segments:
                        for word in segment.words or []:
                            begin=start/1000+word.start;finish=start/1000+word.end
                            midpoint=(begin+finish)*500
                            if core_start<=midpoint<core_end:
                                aligned.append({'word':word.word,'start':begin,'end':finish})
                    hypotheses.append(aligned)
                texts=[' '.join(w['word'].strip() for w in hypothesis) for hypothesis in hypotheses]
                record['candidate']=texts[0];record['independent_decoders_agree']=lexical(texts[0])==lexical(texts[1])
                if lexical(texts[0])==lexical(row['en']):pass
                elif not record['independent_decoders_agree']:record['status']='manual_review_decoder_disagreement'
                elif not insertion_only(row['en'],texts[0]):record['status']='manual_review_not_insertion_only'
                elif not hypotheses[0] or min(w['start'] for w in hypotheses[0])*1000<(original[i-1]['end_ms'] if i else 0) or max(w['end'] for w in hypotheses[0])*1000>core_end:
                    record['status']='manual_review_boundary_conflict'
                else:
                    replacements,review=sentences_from_words(hypotheses[0],nlp,
                        subtitle_options=subtitle_options or table['review'].get('subtitle_policy'))
                    if review['untimed_utterances']:raise ValueError('Unresolved zero duration in repair')
                    for j,replacement in enumerate(replacements,1):
                        replacement['sentence_id']=row['sentence_id'] if len(replacements)==1 else row['sentence_id']+f'_r{j:02d}'
                        replacement['speaker_id']=row['speaker_id']
                        replacement['review_issues']=sorted(set(replacement['review_issues']+['audio_recheck_changed_needs_human_confirmation']))
                        replacement['review_status']='needs_human_review'
                    trial=copy.deepcopy(out);trial['sentences']=rows+replacements+copy.deepcopy(original[i+1:])
                    if validate_sentence_table(trial):raise ValueError('Repair failed final table validation')
                    rows.extend(replacements);applied+=1;record['status']='provisionally_applied_insertion_only'
                    record['replacement_sentence_ids']=[r['sentence_id'] for r in replacements]
                    for item in pending:
                        if item['after_sentence_id']==row['sentence_id']:item['after_sentence_id']=replacements[-1]['sentence_id']
                if record['status']!='provisionally_applied_insertion_only':
                    retained=copy.deepcopy(row)
                    if record['status']!='unchanged':retained['review_issues']=sorted(set(retained['review_issues']+['audio_recheck_difference_needs_human_review']))
                    rows.append(retained)
            except Exception as exc:
                if strict_errors:raise
                record['status']='manual_review_recheck_failed';record['error_type']=type(exc).__name__
                retained=copy.deepcopy(row);retained['review_issues']=sorted(set(retained['review_issues']+['audio_recheck_failed']));rows.append(retained)
            records.append(record)
            logger.info('Audio recheck: checked=%d provisional_insertions=%d',len(records),applied)
    out['sentences']=rows;out['review']['untimed_utterances']=pending
    report={'checked':len(records),'provisional_repairs':applied,'local_transcribe_calls':calls,
            'elapsed_sec':time.perf_counter()-started,'human_confirmed':False,
            'method':'context_audio_redecode_beam5_and_beam1; insertion-only guarded proposals; not independent models',
            'records':records,'raw_asr_timestamps_persisted':False}
    out['review']['audio_recheck']=report
    execution=out['execution'];execution.setdefault('full_video_transcribe_calls',execution['transcribe_calls'])
    execution['local_recheck_transcribe_calls']=execution.get('local_recheck_transcribe_calls',0)+calls
    execution['transcribe_calls']=execution['full_video_transcribe_calls']+execution['local_recheck_transcribe_calls']
    return out


def recheck_node(state):
    from faster_whisper import WhisperModel
    import spacy
    from .common import artifact
    model=WhisperModel(state['request']['model_dir'],device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    nlp=spacy.load('en_core_web_sm',disable=['ner'])
    return {'table':recheck_table(state['table'],artifact(state['job_dir'],state['audio_ref']),model,nlp,state['request'].get('recheck_sentence_ids'))}
