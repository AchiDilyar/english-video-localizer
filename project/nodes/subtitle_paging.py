"""Display-only bilingual pagination at punctuation; never change TTS grouping."""
import os
import re
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont
from subtitle_templates import GEOMETRY,reference_height,style_font


@lru_cache(None)
def template_font(style_id, layout_id):
    """Resolve the actual preset font, including the regular face in Songti's collection."""
    family = style_font(style_id, layout_id)
    filenames = {
        'MiSans': ('MiSans-Regular.ttf', 0),
        'MiSans Medium': ('MiSans-Medium.ttf', 0),
        'MiSans Demibold': ('MiSans-Demibold.ttf', 0),
        'Songti SC': ('Songti.ttc', 6),
    }
    filename, index = filenames[family]
    directories = [
        Path.home() / 'Library/Fonts', Path('/Library/Fonts'),
        Path('/System/Library/Fonts/Supplemental'),
        Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts',
        Path.home() / '.local/share/fonts', Path('/usr/share/fonts'),
    ]
    for directory in directories:
        matches = sorted(directory.rglob(filename)) if directory.is_dir() else []
        if matches:
            return str(matches[0]), index
    raise ValueError(f'字幕模板字体未安装：{family}；请安装字体或配置 display_font_path 用于测量')


@lru_cache(maxsize=1)
def _english_parser():
    import spacy
    return spacy.load('en_core_web_sm', disable=['ner'])


def grammatical_cuts(text):
    """Split finite clauses, not noun coordination or demonstrative 'that'."""
    if not re.search(r'\b(?:and|that|but|because|although|while|which|who)\b',text,re.I):return []
    doc=_english_parser()(text);cuts=[]
    for token in doc:
        if token.lower_ not in {'and','that','but','because','although','while','which','who'}:continue
        head=token.head
        if token.dep_ not in {'cc','mark','nsubj','nsubjpass','dobj','obj'}:continue
        if token.lower_ in {'and','but'}:
            candidates=[t for t in head.conjuncts if t.idx>token.idx and t.pos_ in {'VERB','AUX'}]
            if not candidates:continue
            head=min(candidates,key=lambda t:t.idx)
        if head.pos_ not in {'VERB','AUX'}:continue
        finite=head.tag_ in {'VBD','VBP','VBZ','MD'} or any(t.dep_ in {'aux','auxpass','cop'} for t in head.children)
        subject=any(t.dep_ in {'nsubj','nsubjpass','csubj'} for t in head.children)
        infinitive=(token.lower_ in {'and','but'} and token.i+2<len(doc)
                    and doc[token.i+1].lower_=='to' and doc[token.i+2].pos_=='VERB')
        if not infinitive and (not finite or not subject):continue
        if token.idx>0 and len(text[:token.idx].split())>=2 and len(text[token.idx:].split())>=3:cuts.append(token.idx)
    return cuts


def clauses(text):
    """Preserve all characters; avoid decimals, initials and common abbreviations."""
    ends=[];i=0
    abbreviations={'mr','mrs','ms','dr','prof','sr','jr','st','vs','etc','e.g','i.e'}
    while i<len(text):
        c=text[i];boundary=c in ',;:!?，。；：！？'
        if c==':':boundary=not(i and i+1<len(text) and text[i-1].isdigit() and text[i+1].isdigit())
        if c=='.':
            token=re.search(r'[A-Za-z.]+$',text[:i])
            token=token.group(0) if token else ''
            inside=i and i+1<len(text) and text[i-1].isalnum() and text[i+1].isalnum()
            abbreviation=token.lower() in abbreviations or bool(re.fullmatch(r'(?:[A-Za-z]\.)*[A-Z]',token))
            boundary=not inside and not abbreviation and not(i+1<len(text) and text[i+1]=='.')
        if boundary:
            j=i+1
            while j<len(text) and text[j] in '\"\u201d\u2019\u300b)]）':j+=1
            while j<len(text) and text[j].isspace():j+=1
            ends.append(j);i=j
        else:i+=1
    ends=sorted(set(ends+grammatical_cuts(text)+[len(text)]))
    result=[];start=0
    for end in ends:
        if text[start:end].strip():result.append(text[start:end]);start=end
    return result or [text]


class DisplayMetrics:
    def __init__(self,width,height,font_path=None,*,strict_single_line=False,style_id=None,layout_id='zh_top'):
        self.strict_single_line=strict_single_line
        self.font_index = 0
        if not font_path and style_id is not None:
            font_path, self.font_index = template_font(style_id, layout_id)
        candidates=[font_path] if font_path else [
            str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts/msyh.ttc'),
            '/System/Library/Fonts/PingFang.ttc',
            *sorted(str(path) for path in Path('/System/Library/AssetsV2').glob(
                'com_apple_MobileAsset_Font*/*.asset/AssetData/PingFang.ttc')),
            '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
        self.font_path=next((p for p in candidates if p and Path(p).is_file()),None)
        if not self.font_path:raise ValueError('字幕分页需要可测量字体，请配置 display_font_path')
        self.font_family=self.font(20).getname()[0]
        play_y=reference_height(height);play_x=round(play_y*width/height)
        self.limit=play_x-2*round(GEOMETRY['margin_x']*play_x/GEOMETRY['width'])
        self.sizes={lang:round(GEOMETRY[lang+'_size']*play_y/GEOMETRY['height']) for lang in ['zh','en']}

    @lru_cache(None)
    def font(self,size):return ImageFont.truetype(self.font_path,size=max(1,size),index=self.font_index)

    @lru_cache(None)
    def measure(self,text,lang):return self.font(self.sizes[lang]).getlength(' '.join(text.split()))

    def layout(self,text,lang):
        flat=' '.join(text.split());size=self.sizes[lang]
        if self.measure(flat,lang)<=self.limit:return flat,size,[]
        if lang in {'en','zh'}:
            minimum=round(size*.8)
            while size>minimum and self.font(size).getlength(flat)>self.limit:size-=1
            if self.font(size).getlength(flat)<=self.limit:
                return flat,size,[f'{"english" if lang=="en" else "chinese"}_single_line_with_bounded_font_adjustment']
            size=self.sizes[lang]
        if self.strict_single_line:raise ValueError('SINGLE_LINE_OVERFLOW: split subtitle before rendering')
        cuts=[m.start() for m in re.finditer(r'\s+',flat)] if lang=='en' else [i for i in range(1,len(flat)) if flat[i] not in '，。！？；：、）》”’' and flat[i-1] not in '（《“‘']
        if not cuts:cuts=[len(flat)] # One very long token remains intact.
        cut=min(cuts,key=lambda i:max(self.font(size).getlength(flat[:i].strip()),self.font(size).getlength(flat[i:].strip())))
        if lang=='zh':
            chunks=clauses(flat);punct_cuts=[];at=0
            for chunk in chunks[:-1]:at+=len(chunk);punct_cuts.append(at)
            width_at=lambda i:max(self.font(size).getlength(flat[:i].strip()),self.font(size).getlength(flat[i:].strip()))
            if punct_cuts:
                preferred=min(punct_cuts,key=width_at)
                if width_at(preferred)<=self.limit or width_at(preferred)<=width_at(cut)*1.1:cut=preferred
        lines=[s for s in [flat[:cut].strip(),flat[cut:].strip()] if s]
        while size>1 and max(self.font(size).getlength(s) for s in lines)>self.limit:size-=1
        warnings=['unsplittable_corresponding_clause_displayed_in_two_lines']
        if size<self.sizes[lang]*.65:warnings.append('font_too_small_needs_human_review')
        return '\n'.join(lines),size,warnings


def _partition(zh,en,metrics):
    """Align contiguous whole clauses; never duplicate the shorter language."""
    n,m=len(zh),len(en)
    if n*m>1600:return [(0,n,0,m)]
    z=[0];e=[0]
    for s in zh:z.append(z[-1]+len(s))
    for s in en:e.append(e[-1]+len(s))
    @lru_cache(None)
    def solve(i,j):
        if i==n and j==m:return 0,()
        if i==n or j==m:return float('inf'),()
        best=(float('inf'),())
        for a in range(i+1,n+1):
            for b in range(j+1,m+1):
                zw=metrics.measure(''.join(zh[i:a]),'zh')/metrics.limit
                ew=metrics.measure(''.join(en[j:b]),'en')/metrics.limit
                cost=20*max(0,zw-1)**2+60*max(0,ew-1)**2+.04
                cost+=abs((z[a]-z[i])/max(1,z[-1])-(e[b]-e[j])/max(1,e[-1]))
                tail,parts=solve(a,b)
                if cost+tail<best[0]:best=(cost+tail,((i,a,j,b),)+parts)
        return best
    return list(solve(0,0)[1])


def coalesce_incomplete_parents(cues):
    """Remove old ASR/display cuts inside a clause, within the same TTS group."""
    merged=[]
    def complete(text):return bool(re.search(r'[,.;:!?，。；：！？][\"\u201d\u2019\u300b)]）]*\s*$',text))
    for cue in cues:
        if (merged and not cue.get('semantic_pair_locked') and not cue.get('visual_pair_locked') and not merged[-1].get('semantic_pair_locked') and not merged[-1].get('visual_pair_locked') and cue.get('source_group_id') and cue.get('source_group_id')==merged[-1].get('source_group_id')
                and not (complete(merged[-1]['zh']) and complete(merged[-1]['en']))):
            row=merged[-1];row['zh']+=cue['zh'];row['en']+='\n'+cue['en'];row['end_ms']=cue['end_ms']
            row['audio_text_spans']=row.get('audio_text_spans',[])+cue.get('audio_text_spans',[])
            row['source_segment_ids']=row.get('source_segment_ids',[])+cue.get('source_segment_ids',[])
        else:merged.append({**cue,'audio_text_spans':list(cue.get('audio_text_spans',[]))})
    return merged


def paginate(cues,metrics):
    original=cues;cues=coalesce_incomplete_parents(cues)
    output=[]
    for cue in cues:
        zh,en=clauses(cue['zh']),clauses(cue['en'])
        over=metrics.measure(cue['zh'],'zh')>metrics.limit or metrics.measure(cue['en'],'en')>metrics.limit
        strict=getattr(metrics,'strict_single_line',False)
        if strict:
            from .localize_video.e_single_line import split_pair
            pairs=split_pair({'zh':cue['zh'],'en':cue['en']},metrics)
        else:
            parts=_partition(zh,en,metrics) if over and not cue.get('semantic_pair_locked') else [(0,len(zh),0,len(en))]
            pairs=[{'zh':''.join(zh[a:b]),'en':''.join(en[c:d])} for a,b,c,d in parts]
        duration=cue['end_ms']-cue['start_ms']
        if duration<=0:raise ValueError('字幕显示范围必须为正')
        if duration<10*len(pairs) and not strict:pairs=[{'zh':cue['zh'],'en':cue['en']}]
        if duration<len(pairs):raise ValueError('SINGLE_LINE_TIMING: insufficient positive display time')
        quantum=min(10,max(1,duration//len(pairs)))
        def boundary(offset):
            spans=cue.get('audio_text_spans') or [{'text':cue['zh'],'start_ms':cue['start_ms'],'end_ms':cue['end_ms']}]
            at=0
            for span in spans:
                length=len(span['text'])
                if offset<=at+length:
                    return round(span['start_ms']+(span['end_ms']-span['start_ms'])*(offset-at)/max(1,length))
                at+=length
            return cue['end_ms']
        previous=cue['start_ms'];offset=0
        for index,pair in enumerate(pairs):
            offset+=len(pair['zh'])
            end=boundary(offset) if index+1<len(pairs) else cue['end_ms']
            end=max(previous+quantum,min(end,cue['end_ms']-quantum*(len(pairs)-index-1)))
            row={**cue,'start_ms':previous,'end_ms':end,**pair,
                 'parent_cue_id':cue.get('cue_id'),'subtitle_part':index+1,'subtitle_parts':len(pairs)}
            row['warnings']=list(cue.get('warnings',[]))
            if len(pairs)>1:row['warnings'].append('pagination_time_uses_audio_text_progress; review_alignment')
            if strict:
                row['visual_pair_locked']=True;row['pairing_policy']='ordered_visual_balance'
                if len(pairs)>1:
                    row['semantic_pair_locked']=False
                    row['warnings'].append('strict_single_line_visual_split; per_page_semantic_equivalence_not_required')
            for lang in ['zh','en']:
                display,size,warnings=metrics.layout(row[lang],lang)
                row[lang+'_display']=display;row[lang+'_font_size']=size;row['warnings'].extend(warnings)
            output.append(row);previous=end
    if ''.join(c['zh'] for c in output)!=''.join(c['zh'] for c in original):raise ValueError('分页改变了中文内容')
    if ''.join(c['en'] for c in output)!=''.join(c['en'] for c in cues):
        raise ValueError('分页改变了英文内容')
    if re.sub(r'\s+','',''.join(c['en'] for c in output))!=re.sub(r'\s+','',''.join(c['en'] for c in original)):
        raise ValueError('字幕合并改变了英文内容')
    return output
