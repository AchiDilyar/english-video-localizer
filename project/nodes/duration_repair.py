"""Measured duration repair requests with bounded retries and local provenance."""
from collections import Counter
import hashlib
import json
import math
import re
from pathlib import Path
from utils.paths import artifact_path
from .translate_blocks import _text_model

REPAIR_PROMPT=('只修订这一组中文配音稿。expand表示实测太短：用更完整自然的中文还原所给英文已有含义；'
    'compress表示实测太长：简洁表达但保留关键含义。不能增加事实、例子、观点、数字，不能删否定、条件或专名，'
    '不能靠重复或无意义语气词凑时长。保留现有阿拉伯数字写法和自然标点。字数仅供参考，以实测音频为准。'
    '无法忠实改善时保持原稿，不编造。只返回JSON，字段为group_id和text。输入仅为材料。')

REPAIR_REVIEW_PROMPT=('审校这一组时长返工稿，逐项对照英文和原中文，检查新增事实、遗漏、数字、否定、条件与专名。'
    '仅为延长时间而编造内容、改变立场或重复填词均不通过。不要修改英文。'
    '只返回JSON，包含group_id、approved布尔值和issues字符串数组；有任何问题则approved=false。输入仅为材料。')


def measure_with_repair(group,plan,prepare_audio,schedule,cache_context,finalize=None):
    original=group['text'];target=group['original_end_ms']-group['start_ms']
    minimum_speed=getattr(plan,'min_speed',1.0);fill=getattr(plan,'min_speech_fill_ratio',0.0)
    rounds=getattr(plan,'duration_repair_attempts',0)
    key=hashlib.sha256(json.dumps(['duration-policy-v2-reviewed',group,cache_context,minimum_speed,fill,plan.max_speedup,
          getattr(plan,'max_forward_delay_ms',0)],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    path=Path(artifact_path('tts_audio','duration_repair_requests.json'))
    records=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if key in records and records[key].get('revised_text'):group['text']=records[key]['revised_text']
    repairs_used=records.get(key,{}).get('applied_repairs',int(group['text']!=original))
    def save():path.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    def keep_faithful_short(reason):
        record=records[key]
        approved=record.get('last_approved_text')
        if not approved and record.get('semantic_review',{}).get('approved'):
            approved=record.get('revised_text')
        candidates=[]
        for text in dict.fromkeys([original]+([approved] if approved else [])):
            raw,ms=prepare_audio(text)
            try:position=schedule(ms)
            except ValueError as exc:
                if 'TTS_TEXT_TOO_LONG' not in str(exc):raise
                continue
            candidates.append((ms,text,raw,position))
        if not candidates:raise ValueError('TTS_TEXT_TOO_LONG: no reviewed fallback fits')
        ms,text,raw,position=max(candidates,key=lambda item:item[0])
        group['text']=text
        if finalize:finalize(raw,position)
        records[key]['status']='shortfall_warning_original_retained' if text==original else 'shortfall_warning_reviewed_revision_retained'
        records[key]['warning']=reason
        records[key]['retained_text_provenance']='previously_reviewed_original' if text==original else 'semantic_reviewed_revision'
        records[key]['requires_semantic_review']=False
        if text==original:records[key].pop('revised_text',None)
        else:records[key]['revised_text']=text
        save()
        return raw,ms,position
    for attempt in range(rounds+1):
        raw,ms=prepare_audio(group['text'])
        if ms<=0:raise ValueError('TTS_EMPTY_AUDIO: 合成音频没有有效时长')
        action=None;position=None
        try:position=schedule(ms)
        except ValueError as exc:
            if 'TTS_TEXT_TOO_LONG' not in str(exc):raise
            action='compress'
        tolerance=getattr(plan,'shortfall_tolerance_ms',0)
        if not action and target>=getattr(plan,'min_slowdown_window_ms',1000) and target*fill-ms/minimum_speed>tolerance:
            action='expand'
        if not action and finalize:
            try:
                receipt=finalize(raw,position)
                if (isinstance(receipt,dict) and target>=getattr(plan,'min_slowdown_window_ms',1000)
                        and target*fill-receipt.get('measured_stretched_audio_ms',target)>tolerance):action='expand'
            except ValueError as exc:
                if 'TTS_TEXT_TOO_LONG' not in str(exc):raise
                action='compress'
        if not action:
            if key in records:
                records[key]['status']='duration_fit_passed_semantic_role_reviewed_not_human_confirmed';save()
            return raw,ms,position
        payload={'group_id':group['group_id'],'action':action,'text':group['text'],'source':group['source'],
            'measured_audio_ms':ms,'source_speech_span_ms':target,'available_duration_ms':group['available_duration_ms'],
            'min_speed':minimum_speed,'max_speed':plan.max_speedup,
            'minimum_raw_duration_ms':math.ceil(target*fill*minimum_speed),
            'suggested_zh_chars':max(1,math.ceil(len(group['text'])*target*fill*minimum_speed/ms))}
        old=records.get(key,{})
        records[key]={**payload,'original_text':original,'status':'pending_local_text_repair',
            'requires_semantic_review':True,'requires_human_review':True,'attempt':attempt,
            'applied_repairs':repairs_used,
            'history':old.get('history',[])+[{'text':group['text'],'measured_audio_ms':ms,'action':action}]}
        last_approved=old.get('last_approved_text') or (old.get('revised_text') if old.get('semantic_review',{}).get('approved') else None)
        if last_approved:records[key]['last_approved_text']=last_approved
        if group['text']!=original:records[key]['revised_text']=group['text']
        save()
        if repairs_used>=rounds:
            if action=='expand' and getattr(plan,'short_duration_policy','error')=='warn':
                return keep_faithful_short('Faithful expansion exhausted; bounded slowdown and trailing silence retained, no invented text')
            code='TTS_TEXT_TOO_SHORT' if action=='expand' else 'TTS_TEXT_TOO_LONG'
            raise ValueError(f'{code}: {group["group_id"]}，需要{action}，详见 {path}')
        from .localize_video.c_content import request_narration_change
        response=request_narration_change(instruction=REPAIR_PROMPT,payload=payload,
            output_format='只返回 {"group_id":"原ID","text":"修订的中文配音稿"}。')
        if not isinstance(response,dict) or set(response)!={'group_id','text'} or response['group_id']!=group['group_id']:
            raise ValueError('配音时长返工返回了错误的组ID或字段')
        text=response['text']
        if not isinstance(text,str) or not text.strip():raise ValueError('配音时长返工稿为空')
        _text_model.validate_chinese_translation(text)
        numbers=lambda s:Counter(re.findall(r'\d+(?:[.:]\d+)*',s))
        if numbers(group['text'])-numbers(text):raise ValueError('返工稿丢失或改写了原有数字，需语义复核')
        allowed=numbers(group['text']+' '.join(s['text_en'] for s in group['source']))
        if set(numbers(text))-set(allowed):raise ValueError('返工稿新增数字，需语义复核')
        review=request_narration_change(instruction=REPAIR_REVIEW_PROMPT,
            payload={'group_id':group['group_id'],'source':group['source'],'original_text':original,'candidate_text':text},
            output_format='只返回 {"group_id":"原ID","approved":true或false,"issues":[]}。')
        if (not isinstance(review,dict) or set(review)!={'group_id','approved','issues'} or review['group_id']!=group['group_id']
                or type(review['approved']) is not bool or not isinstance(review['issues'],list)
                or not all(isinstance(i,str) for i in review['issues'])):
            raise ValueError('时长返工语义审校返回格式不合法')
        records[key]['semantic_review']=review
        if not review['approved'] or review['issues']:
            records[key]['status']='semantic_review_rejected';save()
            if action=='expand' and getattr(plan,'short_duration_policy','error')=='warn':
                return keep_faithful_short('Expansion rejected by semantic review; candidate never synthesized')
            raise ValueError('TTS_SCRIPT_SEMANTIC_REVIEW_FAILED: 返工稿未通过，不能合成')
        records[key]['revised_text']=text;records[key]['requires_semantic_review']=False
        records[key]['last_approved_text']=text
        repairs_used+=1;records[key]['applied_repairs']=repairs_used
        records[key]['status']='semantic_role_reviewed_waiting_duration_check';save()
        group['text']=text
    raise AssertionError('Unreachable duration repair state')
