"""Sentence-first timestamps. ASR word/segment times exist only in memory."""
from bisect import bisect_right
import re

from .common import BError,milliseconds,object_hash


def _text(words):return ' '.join(w['word'].strip() for w in words).strip()


def _join(left,right):
    # Only punctuation/case; never add missing spoken words.
    right=right.lstrip()
    if re.match(r'^(You|We|They|He|She|It|This|That|These|Those|Because|Which|Who|Whose|Whom)\b',right):
        right=right[:1].lower()+right[1:]
    return left.rstrip().rstrip('.!?')+' '+right


def review_ranges(ranges,words,nlp):
    """Independent clause/continuation review, not pause-based merging."""
    decisions=[];ranges=[dict(r) for r in ranges]
    i=0
    while i<len(ranges):
        r=ranges[i];text=r['text'];lower=text.strip().lower()
        doc=nlp(text);root=next((t for t in doc if t.dep_=='ROOT'),None)
        # Clause introduced by if/when/etc. cannot finish before its main clause.
        if re.match(r'^(if|unless|although|when|while|provided that)\b',lower) and root is not None and any(t.dep_=='mark' and t.head==root for t in doc) and i+1<len(ranges):
            other=ranges[i+1];r.update({'last':other['last'],'text':_join(text,other['text'])})
            decisions.append({'action':'merge','reason':'subordinate_clause_needs_main_clause','word_count':r['last']-r['first']+1})
            ranges.pop(i+1);i+=1;continue
        relative=bool(re.match(r'^(which|who|whose|whom|because)\b',lower)) and not text.rstrip().endswith('?')
        objectless=bool(re.match(r'^(you|we|they)\s+(can|could|may|might)\s+(do|use|apply|perform)\s+(with|using|in)\b',lower))
        if i and (relative or objectless):
            previous=ranges[i-1]
            if previous['text'].rstrip().endswith('?'):i+=1;continue
            if objectless:
                prev_doc=nlp(previous['text']);lexical=[t for t in prev_doc if not t.is_punct and not t.is_space]
                if not lexical or lexical[-1].pos_ not in ['NOUN','PROPN']:i+=1;continue
            previous.update({'last':r['last'],'text':_join(previous['text'],text)})
            decisions.append({'action':'merge','reason':'relative_or_semantic_continuation','word_count':previous['last']-previous['first']+1})
            ranges.pop(i);i=max(0,i-1);continue
        i+=1
    return ranges,decisions


def sentence_audit(text,nlp):
    doc=nlp(text);roots=[t for t in doc if t.dep_=='ROOT'];issues=[]
    if not text.strip():return ['empty_text']
    conversational=bool(re.fullmatch(r'\s*(okay|ok|yes|no|thanks|thank you|right|great|sure|hello|good morning)[.!?]*\s*',text,re.I))
    if not conversational and (not roots or all(t.pos_ not in ['VERB','AUX'] for t in roots)):
        issues.append('possible_fragment_or_elliptical_utterance')
    if re.match(r'^\s*(which|who|whose|whom|because)\b',text,re.I) and not text.rstrip().endswith('?'):
        issues.append('possible_unattached_dependent_clause')
    if roots and roots[0].tag_ in ['VBG','VBN'] and not any(t.dep_ in ['aux','auxpass'] for t in roots[0].children):
        issues.append('possible_nonfinite_fragment')
    if roots and re.match(r'^\s*(if|unless|although|when|while)\b',text,re.I) and any(t.dep_=='mark' and t.head==roots[0] for t in doc):
        issues.append('possible_missing_main_clause')
    if not re.search(r'[.!?][\"\u201d\u2019\x27]*\s*$',text):issues.append('possible_unfinished_sentence')
    return issues


def sentences_from_words(words,nlp,semantic_reviewer=None):
    if not words:raise BError('WORD_ALIGNMENT_MISSING','Word alignment is required to time complete sentences')
    tokens=[w['word'].strip() for w in words]
    if any(not t for t in tokens):raise BError('WORD_ALIGNMENT_INVALID','Blank aligned word token')
    text=' '.join(tokens);starts=[];ends=[];position=0
    for token in tokens:
        starts.append(position);ends.append(position+len(token));position+=len(token)+1
    doc=nlp(text);ranges=[]
    for sentence in doc.sents:
        first=max(0,bisect_right(ends,sentence.start_char))
        last=max(first,bisect_right(starts,sentence.end_char-1)-1)
        # Parser boundaries inside one aligned token are merged, never duplicated.
        if ranges and first<=ranges[-1]['last']:
            ranges[-1]['last']=last;ranges[-1]['text']=_text(words[ranges[-1]['first']:last+1])
        else:ranges.append({'first':first,'last':last,'text':_text(words[first:last+1])})
    ranges,decisions=review_ranges(ranges,words,nlp)
    from .semantic_review import refine_ranges
    ranges,semantic_report=refine_ranges(ranges,words,semantic_reviewer,nlp)
    if [i for r in ranges for i in range(r['first'],r['last']+1)]!=list(range(len(words))):
        raise BError('SENTENCE_COVERAGE','Sentence construction omitted or duplicated aligned words')
    expected=re.findall(r"[\w']+",text.lower());actual=re.findall(r"[\w']+",' '.join(r['text'] for r in ranges).lower())
    if expected!=actual:raise BError('SENTENCE_TEXT_CHANGED','Review must not add/remove/replace spoken words')
    rows=[];untimed=[]
    for i,r in enumerate(ranges,1):
        selected=words[r['first']:r['last']+1]
        begin=milliseconds(min(w['start'] for w in selected));end=milliseconds(max(w['end'] for w in selected))
        if begin>=end:
            untimed.append({'en':r['text'],'after_sentence_id':rows[-1]['sentence_id'] if rows else None,
                            'reason':'alignment_has_no_positive_duration; assign final time by listening'})
            continue
        issues=sentence_audit(r['text'],nlp)+r.get('semantic_issues',[])
        if len(selected)>32:issues.append('subtitle_unit_too_long')
        if end-begin>10000:issues.append('subtitle_unit_duration_too_long')
        if i==1 and issues:issues.append('video_start_may_be_partial')
        if i==len(ranges) and issues:issues.append('video_end_may_be_partial')
        rows.append({'sentence_id':f'sentence_{len(rows)+1:06d}','start_ms':begin,'end_ms':end,
                     'en':r['text'],'speaker_id':None,'review_status':'needs_human_review' if issues else 'automatic_checks_passed',
                     'review_issues':issues})
    # No original alignment, token ranges or superseded timestamps returned.
    return rows,{'method':'spacy_dependency_sentence_parse_plus_clause_review_v2',
                 'coverage_word_count':len(words),'spoken_text_sha256':object_hash(tokens),
                 'lexical_coverage_checked':True,'automatic_repairs':decisions,
                 'semantic_review':semantic_report,
                 'untimed_utterances':untimed,
                 'original_asr_timestamps_persisted':False}


def validate_sentence_table(table):
    errors=[]
    if table.get('schema_version')!='b-sentences-2':return ['Unsupported sentence-only schema']
    previous=0;ids=[]
    for s in table.get('sentences',[]):
        ids.append(s['sentence_id'])
        if type(s['start_ms']) is not int or type(s['end_ms']) is not int or not 0<=s['start_ms']<s['end_ms']<=table['duration_ms']:
            errors.append('Invalid sentence time range')
        if s['start_ms']<previous:errors.append('Overlapping sentence boundaries require review')
        previous=s['end_ms']
        if not s['en'].strip():errors.append('Empty sentence')
    if not ids:errors.append('No sentences')
    if len(ids)!=len(set(ids)):errors.append('Duplicate sentence IDs')
    for forbidden in ['original_segments','segments','words','sentence_groups']:
        if forbidden in table:errors.append('Original ASR structures must not be exported')
    if table.get('diarization'):
        diarization=table['diarization'];known=set(diarization['speaker_ids'])
        for turn in diarization['turns']:
            if turn['speaker_id'] not in known or type(turn['start_ms']) is not int or type(turn['end_ms']) is not int or not 0<=turn['start_ms']<turn['end_ms']<=table['duration_ms']:
                errors.append('Invalid speaker turn')
        if any(s['speaker_id'] is not None and s['speaker_id'] not in known for s in table['sentences']):errors.append('Unknown speaker ID')
    return sorted(set(errors))
