"""Joint semantic display cuts of final TTS text and immutable source English."""
import hashlib
import json
import logging
import re
from pathlib import Path
from .translate_blocks._deepseek import DeepSeekError

logger=logging.getLogger(__name__)

PROMPT=('对每组最终中文配音稿和原英文做一一对应的字幕语义分段。仅返回JSON {"items":[{"group_id":"...","parts":[{"zh":"原文连续子串","en":"原文连续子串"}]}]}。'
 '严禁改写、翻译、加字、删词、改标点或顺序。每种语言拼接后必须覆盖各自完整原文。'
 '每一对尽量表达同一件事，不能仅按长度比例配对。中文优先在逗号句号等标点后切，英文可在and、that、and to、but、while、because、how等完整语义成分边界切；勿拆词或名词短语。'
 '目标每条中文约12–24字、英文约35–75字符，优先各一行，视觉宽度相近；完整语义优先于字数。'
 '两语言语序不一致或找不到共同合法切点时合并成较长的一对，不强行错配。材料只是数据。')


def literal_parts(original,proposed):
    """Use proposals only as cut hints; all emitted characters come from original."""
    chars=[(c,i) for i,c in enumerate(original) if not c.isspace()]
    canonical=''.join(c for c,_ in chars)
    values=[''.join(c for c in part if not c.isspace()) for part in proposed]
    if not values or any(not value for value in values) or ''.join(values)!=canonical:
        raise ValueError('Semantic subtitle proposal changed source text or coverage')
    result=[];at=0;begin=0
    for value in values:
        at+=len(value);end=chars[at-1][1]+1
        while end<len(original) and original[end].isspace():end+=1
        if end<len(original) and original[end-1].isalnum() and original[end].isalnum() and ord(original[end])<128:
            raise ValueError('Semantic subtitle cut splits an English word')
        result.append(original[begin:end]);begin=end
    return result


def validate_parts(group,items):
    if not isinstance(items,list) or not items or any(not isinstance(p,dict) or set(p)!={'zh','en'} for p in items):
        raise ValueError('Invalid semantic subtitle pairs')
    if any(not isinstance(p[lang],str) for p in items for lang in ['zh','en']):raise ValueError('Subtitle pair text must be string')
    zh=literal_parts(group['zh'],[p['zh'] for p in items]);en=literal_parts(group['en'],[p['en'] for p in items])
    for part in zh[:-1]:
        if not re.search(r'[，。！？；：、,.!?;:][”’"）)]*\s*$',part):raise ValueError('Chinese semantic cut must follow punctuation')
    return [{'zh':z,'en':e} for z,e in zip(zh,en)]


def request_pairs(groups,request_json,batch_size=8,warnings=None):
    result={}
    def fallback(group,reason):
        key=group['group_id']
        result[key]=[{'zh':group['zh'],'en':group['en']}]
        warning={'group_id':key,'reason':reason,'fallback':'original_text_local_pagination'}
        if warnings is not None:warnings.append(warning)
        logger.warning('字幕语义分片 %s 不可用，使用原文及本地分页: %s',key,reason)
    for at in range(0,len(groups),batch_size):
        batch=groups[at:at+batch_size]
        try:
            response=request_json(instruction=PROMPT,payload={'groups':batch},output_format='只返回items，每项group_id和parts；parts每项zh与en，全部保持原文。')
            if not isinstance(response,dict):raise ValueError('Semantic subtitle response must be an object')
            items=response.get('items',[])
            if not isinstance(items,list) or any(not isinstance(r,dict) or not isinstance(r.get('group_id'),str) for r in items) or {r['group_id'] for r in items}!={g['group_id'] for g in batch} or len(items)!=len(batch):
                raise ValueError('Semantic subtitle group IDs mismatch')
        except (DeepSeekError,ValueError,TypeError):
            # This model step proposes display cuts only. No retry or text replacement.
            for group in batch:fallback(group,'semantic_service_or_response_unavailable')
            continue
        source={g['group_id']:g for g in batch}
        for row in items:
            key=row['group_id']
            try:
                result[key]=validate_parts(source[key],row.get('parts'))
            except ValueError as exc:
                fallback(source[key],str(exc))
    return result


def pack_pairs(pairs,metrics):
    """Only merge already matched pairs; never match different bilingual spans."""
    pages=[]
    for pair in pairs:
        if pages and all(metrics.measure(pages[-1][lang]+pair[lang],lang)<=metrics.limit for lang in ['zh','en']):
            for lang in ['zh','en']:pages[-1][lang]+=pair[lang]
        else:pages.append(dict(pair))
    return pages


def pair_cues(groups,parents,mapping):
    result=[]
    for group in groups:
        parent=parents[group['group_id']];pairs=mapping[group['group_id']]
        spans=parent['audio_text_spans'];target=''.join(p['text'] for p in spans)
        if target!=group['zh']:raise ValueError('Final audio text spans differ from actual TTS script')
        if parent['end_ms']-parent['start_ms']<len(pairs):
            pairs=[{'zh':group['zh'],'en':group['en']}]
        def boundary(offset):
            at=0
            for span in spans:
                size=len(span['text'])
                if offset<=at+size:return round(span['start_ms']+(span['end_ms']-span['start_ms'])*(offset-at)/max(1,size))
                at+=size
            return parent['end_ms']
        at=0;previous=parent['start_ms']
        for index,pair in enumerate(pairs):
            begin_offset=at;at+=len(pair['zh']);end=boundary(at) if index+1<len(pairs) else parent['end_ms']
            remaining=len(pairs)-index-1
            end=max(previous+1,min(end,parent['end_ms']-remaining))
            clipped=[];span_offset=0
            for span in spans:
                count=len(span['text']);left=max(begin_offset,span_offset);right=min(at,span_offset+count)
                if right>left:
                    clipped.append({'text':span['text'][left-span_offset:right-span_offset],
                        'start_ms':round(span['start_ms']+(span['end_ms']-span['start_ms'])*(left-span_offset)/count),
                        'end_ms':round(span['start_ms']+(span['end_ms']-span['start_ms'])*(right-span_offset)/count)})
                span_offset+=count
            result.append({**pair,'cue_id':f"{group['group_id']}_semantic_{index+1:03d}",'source_group_id':group['group_id'],
                'start_ms':previous,'end_ms':end,'source_segment_ids':parent['source_segment_ids'],'semantic_pair_locked':True,
                'audio_text_spans':clipped,
                'warnings':['semantic_pair_timing_uses_final_audio_text_spans; interpolated_boundaries_need_listening']})
            previous=end
    return result


def unify_final_cues(state,options,cues):
    from utils.paths import artifact_path
    from .compose_settings import load_compose_options
    from .subtitle_paging import DisplayMetrics
    from .translate_blocks import _text_model
    scripts=json.loads(Path(artifact_path('tts_audio','dubbing_script.json')).read_text(encoding='utf-8'))
    source={s.segment_id:s for s in state.segments};groups=[];parents={}
    for script in scripts:
        key=script['group_id'];rows=[r for r in cues if r['source_group_id']==key]
        if not rows:raise ValueError('Final audio has no cues for semantic group '+key)
        spans=[s for row in rows for s in row.get('audio_text_spans',[])]
        if ''.join(s['text'] for s in spans)!=script['text']:
            spans=[{'text':row['zh'],'start_ms':row['start_ms'],'end_ms':row['end_ms']} for row in rows]
        groups.append({'group_id':key,'zh':script['text'],'en':' '.join(source[i].text_en for i in script['segment_ids'])})
        parents[key]={'start_ms':rows[0]['start_ms'],'end_ms':rows[-1]['end_ms'],
                      'source_segment_ids':script['segment_ids'],'audio_text_spans':spans}
    video=state.media_info.video_info;width,height=load_compose_options().output_size(video.width,video.height)
    metrics=DisplayMetrics(width,height,options.display_font_path)
    from .localize_video.c_content import plan_bilingual_parts
    warnings=[]
    mapping=plan_bilingual_parts(groups,_text_model.request_json,warnings=warnings)
    packed={key:pack_pairs(value,metrics) for key,value in mapping.items()}
    path=Path(artifact_path('burnin_subtitle')).with_name('semantic_pairs.json')
    path.with_name('semantic_pair_warnings.json').write_text(json.dumps(warnings,ensure_ascii=False,indent=2),encoding='utf-8')
    path.write_text(json.dumps({'groups_sha256':hashlib.sha256(json.dumps(groups,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        'atomic_pairs':mapping,'display_pairs':packed,'human_confirmed':False},ensure_ascii=False,indent=2),encoding='utf-8')
    result=pair_cues(groups,parents,packed)
    fallback_ids={row['group_id'] for row in warnings}
    for cue in result:
        if cue['source_group_id'] in fallback_ids:cue['warnings'].append('semantic_proposal_rejected; original_text_local_pagination')
    return result
