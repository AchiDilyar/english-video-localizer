"""Local refinement and explicitly marked PCM-grounded subtitle recovery."""
from array import array
import difflib
import hashlib
import json
import logging
import sys
import time
import unicodedata
import wave
from pathlib import Path
from utils.paths import artifact_path
logger=logging.getLogger(__name__)


def normalize(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def restore_script_text(cues,script):
    """Known submitted TTS text; observed audio cue times. Never backtranslate.

    Character matches locate cue cuts, with interpolation for ASR errors.
    This is cue alignment, not independently verified word-level forced alignment.
    """
    if not cues or not script.strip():raise ValueError('缺少实际语音范围或配音稿，不能生成字幕')
    known=normalize(script);observed=normalize(''.join(c['zh'] for c in cues))
    if not known:raise ValueError('配音稿没有有效文本')
    positions=[i for i,c in enumerate(script) if normalize(c)]
    anchors={0:0,len(observed):len(known)}
    for block in difflib.SequenceMatcher(None,known,observed,autojunk=False).get_matching_blocks():
        for k in range(block.size+1):
            anchors[block.b+k]=max(anchors.get(block.b+k,0),block.a+k)
    anchors[0]=0;anchors[len(observed)]=len(known)
    points=sorted(anchors.items())
    def cut(q):
        if q<=0:return 0
        if q>=len(observed):return len(known)
        for (x,a),(y,b) in zip(points,points[1:]):
            if x<=q<=y:return round(a+(b-a)*(q-x)/(y-x))
        raise ValueError('无法对应配音稿和语音范围')
    output=[];offset=0;previous_cut=0
    for i,cue in enumerate(cues):
        offset+=len(normalize(cue['zh']))
        end=cut(offset) if i+1<len(cues) else len(known)
        begin_raw=0 if previous_cut==0 else positions[previous_cut] if previous_cut<len(positions) else len(script)
        end_raw=positions[end] if end<len(positions) else len(script)
        if end==previous_cut:
            if output:
                output[-1]['end_ms']=cue['end_ms']
                output[-1].setdefault('warnings',[]).append('unmatched_ASR_cue_time_merged; text not retained')
            continue
        row=dict(cue)
        row.update({'zh':script[begin_raw:end_raw],'text_policy':'verbatim_submitted_TTS_script; final_audio_cue_times'})
        if cue.get('alignment_method','').startswith('known_TTS_script'):
            row['alignment_input_text']=cue['zh']
        else:row.setdefault('asr_original_text',cue['zh'])
        if known!=observed:row.setdefault('warnings',[]).append('script_text_aligned_across_ASR_differences; not verified word alignment')
        output.append(row);previous_cut=end
    if ''.join(c['zh'] for c in output)!=script:raise ValueError('配音稿字幕覆盖校验失败')
    return output


def group_audio(report):
    path=Path(artifact_path('tts_audio',report['group_id']+'.wav'))
    with wave.open(str(path),'rb') as f:
        if f.getnchannels()!=1 or f.getsampwidth()!=2:raise ValueError('字幕对齐需要单声道 PCM16')
        rate=f.getframerate();frames=f.readframes(f.getnframes())
    with wave.open(str(artifact_path('dub_audio')),'rb') as f:
        if f.getframerate()!=rate or f.getnchannels()!=1 or f.getsampwidth()!=2:
            raise ValueError('分组与最终音轨规格不同')
        f.setpos(round(report['start_ms']*rate/1000))
        if f.readframes(len(frames)//2)!=frames:raise ValueError('分组 PCM 与最终音轨内容不一致')
    if not frames:raise ValueError('字幕不能为无声空音频编造时间')
    return path,rate,frames


def waveform_cue(report,text):
    """Use actual final PCM activity bounds, never the old English timestamps."""
    _,rate,frames=group_audio(report)
    samples=array('h');samples.frombytes(frames)
    if sys.byteorder!='little':samples.byteswap()
    peak=max(map(abs,samples))
    if peak<64:raise ValueError('没有可核对的有效音频信号，不能编造字幕时间')
    threshold=max(4,peak/10000)
    first=next(i for i,x in enumerate(samples) if abs(x)>threshold)
    last=len(samples)-1-next(i for i,x in enumerate(reversed(samples)) if abs(x)>threshold)
    start=report['start_ms']+max(0,int(first*1000/rate)-20)
    end=min(report['end_ms'],report['start_ms']+round((last+1)*1000/rate)+20)
    if end<=start:raise ValueError('实际波形没有有效显示范围')
    return {'cue_id':'pcm_'+report['group_id'],'start_ms':start,'end_ms':end,'zh':text,
            'alignment_method':'known_TTS_script_with_final_PCM_activity_bounds',
            'warnings':['needs_human_review: text comes from TTS script; activity bounds are not independent word ASR'],
            'pcm_sha256':hashlib.sha256(frames).hexdigest()}


def refine_groups(reports,scripts,audio_hash,model_dir):
    """One local model instance; cache evidence, reject mismatched/hallucinated text."""
    from .speech_subtitles import split_words
    file=Path(artifact_path('burnin_subtitle')).with_name('group_audio_asr.json')
    previous=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    entries=previous.get('groups',{}) if previous.get('audio_sha256')==audio_hash and previous.get('model_dir')==str(model_dir) else {}
    model=None;calls=0;started=time.perf_counter();result={}
    for report in reports:
        key=report['group_id'];path,rate,frames=group_audio(report)
        digest=hashlib.sha256(frames).hexdigest();entry=entries.get(key)
        if not entry or entry.get('pcm_sha256')!=digest:
            if model is None:
                from faster_whisper import WhisperModel
                model=WhisperModel(str(model_dir),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
            stream,_=model.transcribe(str(path),language='zh',beam_size=5,temperature=0,
                word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
            words=[]
            for segment in stream:
                for w in segment.words or []:
                    if w.word.strip():words.append({'text':w.word.strip(),
                        'start_ms':max(0,round(w.start*1000)),
                        'end_ms':min(report['end_ms']-report['start_ms'],round(w.end*1000))})
            calls+=1
            try:cues=split_words(words)
            except ValueError:cues=[] # Explicitly recorded invalid ASR timing; use verified PCM fallback below.
            recognized=''.join(c['zh'] for c in cues)
            a,b=normalize(recognized),normalize(scripts[key])
            similarity=difflib.SequenceMatcher(None,a,b,autojunk=False).ratio()
            accepted=bool(cues) and (a==b if len(b)<=4 else similarity>=.65)
            accepted=accepted and all(0<=c['start_ms']<c['end_ms']<=report['end_ms']-report['start_ms'] for c in cues)
            accepted=accepted and all(a['end_ms']<=b['start_ms'] for a,b in zip(cues,cues[1:]))
            entry={'pcm_sha256':digest,'recognized_text':recognized,'similarity_to_TTS_script':similarity,
                   'accepted':accepted,'local_cues':cues}
            entries[key]=entry
            logger.info('局部字幕核对 %s：匹配 %.3f，ASR采纳=%s',key,similarity,accepted)
            file.write_text(json.dumps({'audio_sha256':audio_hash,'model_dir':str(model_dir),
                'groups':entries,'latest_run_calls':calls,'latest_run_elapsed_sec':time.perf_counter()-started,
                'audio_uploaded':False,'human_confirmed':False},ensure_ascii=False,indent=2),encoding='utf-8')
        if entry['accepted']:
            result[key]=[{**cue,'cue_id':key+'_'+str(i),'start_ms':report['start_ms']+cue['start_ms'],
                          'end_ms':report['start_ms']+cue['end_ms'],'alignment_method':'local_ASR_on_final_group_PCM',
                          'warnings':['local_ASR_refinement; not human confirmed']} for i,cue in enumerate(entry['local_cues'])]
        else:result[key]=[waveform_cue(report,scripts[key])]
    return result
