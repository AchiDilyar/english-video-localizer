"""Generate bilingual subtitle cues after locally recognizing the final dub."""
import hashlib
import json
import re
import time
import wave
import unicodedata
import difflib
from functools import lru_cache
from pathlib import Path

from utils.paths import artifact_path


def pair_original_english(cues,source_rows):
    """Only group whole original sentences; never generate or rewrite English."""
    if not cues or not source_rows:raise ValueError('原英文或语音字幕缺失，不能静默丢弃内容')
    normalize=lambda text:''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))
    # Partition the longer sequence into contiguous nonempty blocks. Similarity
    # uses Chinese for correspondence only; English always comes from text_en.
    source_long=len(source_rows)>=len(cues)
    longer=source_rows if source_long else cues
    shorter=cues if source_long else source_rows
    def text(rows,is_source):
        return normalize(''.join(r['zh_subtitle'] if is_source else r['zh'] for r in rows))
    @lru_cache(None)
    def best(i,j):
        if j==len(shorter):return (0,()) if i==len(longer) else (float('inf'),())
        result=(float('inf'),())
        for end in range(i+1,len(longer)-(len(shorter)-j-1)+1):
            a=text(longer[i:end],source_long)
            b=text(shorter[j:j+1],not source_long)
            tail,cuts=best(end,j+1)
            value=1-difflib.SequenceMatcher(None,a,b,autojunk=False).ratio()+tail
            if value<result[0]:result=(value,(end,)+cuts)
        return result
    _,cuts=best(0,0)
    output=[];begin=0
    for j,end in enumerate(cuts):
        originals=source_rows[begin:end] if source_long else source_rows[j:j+1]
        spoken=cues[j:j+1] if source_long else cues[begin:end]
        row=dict(spoken[0])
        row.update({'end_ms':spoken[-1]['end_ms'],'zh':''.join(r['zh'] for r in spoken),
                    'en':'\n'.join(r['text_en'] for r in originals),
                    'source_segment_ids':[r['segment_id'] for r in originals],
                    'audio_text_spans':[{'text':r['zh'],'start_ms':r['start_ms'],'end_ms':r['end_ms']} for r in spoken],
                    'english_policy':'verbatim_source; grouping_only'})
        output.append(row);begin=end
    return output


def split_words(words,max_chars=18,max_duration_ms=3500):
    cues=[];selected=[]
    def flush():
        nonlocal selected
        if not selected:return
        text=''.join(w['text'] for w in selected).strip()
        start=min(w['start_ms'] for w in selected);end=max(w['end_ms'] for w in selected)
        if start>=end:
            if cues:
                cues[-1]['zh']+=text
                cues[-1].setdefault('warnings',[]).append('zero_duration_suffix_attached')
            else:raise ValueError('最终中文音轨存在无法定时的首词')
        else:cues.append({'cue_id':f'speech_{len(cues)+1:04d}','start_ms':start,'end_ms':end,'zh':text})
        selected=[]
    for word in words:
        if selected and (len(''.join(w['text'] for w in selected))+len(word['text'])>max_chars
                         or word['end_ms']-selected[0]['start_ms']>max_duration_ms):flush()
        selected.append(word)
        if re.search(r'[，。！？；,.!?;]$',word['text']):flush()
    flush()
    return cues


def recognize_final_audio(state,model_dir):
    audio=Path(artifact_path('dub_audio'))
    if not audio.is_file():raise FileNotFoundError('先生成最终中文配音，再生成字幕')
    audio_hash=hashlib.sha256(audio.read_bytes()).hexdigest()
    cache=Path(artifact_path('burnin_subtitle')).with_name('final_audio_asr.json')
    model_dir=str(Path(model_dir).resolve())
    if cache.exists():
        previous=json.loads(cache.read_text(encoding='utf-8'))
        if previous['audio_sha256']==audio_hash and previous['model_dir']==model_dir and previous.get('segmentation_version')==2:return previous
    from utils.local_models import require_whisper_model
    model_dir = require_whisper_model(model_dir)
    from faster_whisper import WhisperModel
    started=time.perf_counter()
    with wave.open(str(audio),'rb') as handle:
        long_audio=handle.getnframes()/handle.getframerate()>60
    model=WhisperModel(model_dir,device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    stream,_=model.transcribe(str(audio),language='zh',beam_size=5,temperature=0,
                             word_timestamps=True,vad_filter=long_audio,condition_on_previous_text=False)
    words=[]
    for segment in stream:
        if segment.text.strip() and not segment.words:raise ValueError('最终配音识别缺少词时间')
        for w in segment.words or []:
            if w.word.strip():words.append({'text':w.word.strip(),'start_ms':round(w.start*1000),'end_ms':round(w.end*1000)})
    if not words:raise ValueError('最终中文配音中没有识别到有效语音')
    with wave.open(str(audio),'rb') as f:duration=round(f.getnframes()*1000/f.getframerate())
    cues=split_words(words)
    if any(not 0<=r['start_ms']<r['end_ms']<=duration for r in cues):raise ValueError('最终语音字幕时间超出音轨')
    if any(a['end_ms']>b['start_ms'] for a,b in zip(cues,cues[1:])):raise ValueError('最终语音字幕重叠')
    result={'audio_sha256':audio_hash,'model_dir':model_dir,'language':'zh','cues':cues,'segmentation_version':2,
            'elapsed_sec':time.perf_counter()-started,'local_inference_calls':1,'audio_uploaded':False,
            'method':'local_ASR_on_final_postprocessed_dub','human_confirmed':False}
    cache.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def create_bilingual_cues(state,model_dir):
    asr=recognize_final_audio(state,model_dir)
    script_path=Path(artifact_path('tts_audio','dubbing_script.json'))
    report_path=Path(artifact_path('tts_audio','alignment_report.json'))
    script=json.loads(script_path.read_text(encoding='utf-8')) if script_path.exists() else []
    reports=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else []
    source={s.segment_id:s.text_en for s in sorted(state.segments,key=lambda s:s.start_ms)}
    reviewed={s.segment_id:s.zh_subtitle for s in state.reviewed_blocks}
    script_by_id={g['group_id']:g['text'] for g in script}
    items=[]
    for cue in asr['cues']:
        overlaps=[(max(0,min(cue['end_ms'],r['end_ms'])-max(cue['start_ms'],r['start_ms'])),r) for r in reports if 'group_id' in r]
        group=max(overlaps,key=lambda pair:pair[0])[1] if overlaps and max(p[0] for p in overlaps)>0 else None
        if group:
            # ASR edges may drift into the neighboring group's silence. The
            # actual PCM placement bounds are known, unlike original B timings.
            cue=dict(cue)
            cue['start_ms']=max(cue['start_ms'],group['start_ms'])
            cue['end_ms']=min(cue['end_ms'],group['end_ms'])
            if cue['start_ms']>=cue['end_ms']:raise ValueError('语音识别与实际音轨分组无法对应')
            expected=script_by_id.get(group['group_id'],'')
            normalize=lambda text:''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))
            a,b=normalize(cue['zh']),normalize(expected)
            if len(a)==len(b) and len(a)>=5 and sum(x!=y for x,y in zip(a,b))==1:
                cue['asr_original_text']=cue['zh']
                cue['zh']=expected
                cue.setdefault('warnings',[]).append('one_character_corrected_against_known_TTS_script')
            # Keep the final cue timing/text in the generated output, while the
            # recognition cache above remains the original local ASR evidence.
            asr['cues'][int(cue['cue_id'].split('_')[-1])-1]=cue
        cue=dict(cue)
        cue['source_group_id']=group['group_id'] if group else 'all'
        items.append(cue)
    from .speech_alignment import normalize,refine_groups,restore_script_text
    needs_refinement=[]
    for report in reports:
        key=report['group_id'];spoken=[cue for cue in items if cue['source_group_id']==key]
        a,b=normalize(''.join(c['zh'] for c in spoken)),normalize(script_by_id.get(key,''))
        if not spoken or (b and (a!=b if len(b)<=4 else difflib.SequenceMatcher(None,a,b,autojunk=False).ratio()<.55)):
            needs_refinement.append(report)
    refined=refine_groups(needs_refinement,script_by_id,asr['audio_sha256'],str(Path(model_dir).resolve())) if needs_refinement else {}
    cues=[]
    for report in [r for r in reports if 'group_id' in r] or [{'group_id':'all','segment_ids':list(source)}]:
        spoken=[cue for cue in items if cue['source_group_id']==report['group_id']]
        if report['group_id'] in refined:spoken=refined[report['group_id']]
        if report['group_id'] in script_by_id:
            spoken=restore_script_text(spoken,script_by_id[report['group_id']])
        originals=[{'segment_id':key,'text_en':source[key],'zh_subtitle':reviewed[key]} for key in report['segment_ids']]
        paired=pair_original_english(spoken,originals)
        for row in paired:row['source_group_id']=report['group_id']
        cues.extend(paired)
    if re.findall(r'\S+',' '.join(row['en'] for row in cues))!=re.findall(r'\S+',' '.join(source.values())):
        raise ValueError('英文原文覆盖校验失败：不允许改写、遗漏、重复或调序')
    path=Path(artifact_path('burnin_subtitle')).with_name('speech_cues.json')
    warnings=[{'group_id':key,'method':value[0]['alignment_method'],'warnings':value[0].get('warnings',[])} for key,value in refined.items()]
    path.with_name('alignment_warnings.json').write_text(json.dumps(warnings,ensure_ascii=False,indent=2),encoding='utf-8')
    path.with_name('alignment_warnings.txt').write_text('全部中文字幕文字取实际提交的配音稿，时间按最终音频对齐。以下条目已用局部识别或最终波形范围补齐，不代表逐词人工确认。\n'+
        '\n'.join(f"{w['group_id']}: {w['method']} — {'; '.join(w['warnings'])}" for w in warnings),encoding='utf-8')
    path.write_text(json.dumps({'audio_sha256':asr['audio_sha256'],'method':'submitted_TTS_script_aligned_to_final_audio_using_local_ASR_and_marked_PCM_recovery',
                               'refinement_groups':len(refined),'warnings':warnings,'cues':cues,
                               'human_confirmed':False,'script_reference':script},ensure_ascii=False,indent=2),encoding='utf-8')
    return cues


def render_speech_subtitles(state,options,model_dir):
    cues=create_bilingual_cues(state,model_dir)
    if getattr(options,'semantic_pairing',False):
        from .semantic_subtitles import unify_final_cues
        cues=unify_final_cues(state,options,cues)
    return render_cue_tracks(state,options,cues)


def render_cue_tracks(state,options,cues):
    from .subtitle_cover import _timestamp,_write_tracks
    from .compose_settings import load_compose_options
    from subtitle_templates import ass_header,ass_dialogue,ass_times
    tracks={name:[] for name in ['english_srt','chinese_srt','bilingual_srt']}
    dialogue=[]
    video=state.media_info.video_info
    width,height=load_compose_options().output_size(video.width,video.height)
    metrics=None
    if options.paginate:
        from .subtitle_paging import DisplayMetrics,paginate
        metrics=DisplayMetrics(width,height,options.display_font_path,strict_single_line=getattr(options,'strict_single_line',False))
        cues=paginate(cues,metrics)
        Path(artifact_path('burnin_subtitle')).with_name('display_cues.json').write_text(
            json.dumps({'cues':cues,'font_family':metrics.font_family,'width':width,'height':height,
                        'affects_dubbing':False,'timing_note':'punctuation cuts follow audio text spans; interpolated cuts need review'},ensure_ascii=False,indent=2),encoding='utf-8')
        small=[c for c in cues if 'font_too_small_needs_human_review' in c['warnings']]
        Path(artifact_path('burnin_subtitle')).with_name('display_warnings.txt').write_text(
            '分页仅改变显示，不改变配音。无合法双语切点时最多两行保留完整分句；时间插值处需回听核对。\n'
            '以下条目为较小字号，需人工检查：\n'+'\n'.join(
                f"{c['start_ms']/1000:.3f}–{c['end_ms']/1000:.3f}秒: {c['zh']} | {c['en']}" for c in small),encoding='utf-8')
    for i,cue in enumerate(cues,1):
        header=f"{i}\n{_timestamp(cue['start_ms'])} --> {_timestamp(cue['end_ms'])}\n"
        english=cue.get('en_display',cue['en']);chinese=cue.get('zh_display',cue['zh'])
        tracks['english_srt'].append(header+english)
        tracks['chinese_srt'].append(header+chinese)
        tracks['bilingual_srt'].append(header+chinese+'\n'+english)
        begin,end=ass_times(cue['start_ms'],cue['end_ms'])
        dialogue.append(ass_dialogue(begin,end,chinese,english,options.layout,fade_enabled=options.fade_enabled,
                                     render_height=height,wrap_english=not options.paginate,wrap_chinese=not options.paginate,
                                     font_sizes={lang:cue[lang+'_font_size'] for lang in ['zh','en']} if metrics else None))
    outputs={key:'\n\n'.join(values)+'\n' for key,values in tracks.items()}
    video=state.media_info.video_info
    width,height=load_compose_options().output_size(video.width,video.height)
    outputs['burnin_subtitle']=ass_header(metrics.font_family if metrics else None,width,height,options.style,options.layout)+'\n'.join(dialogue)+'\n'
    _write_tracks(outputs)
    return {}
