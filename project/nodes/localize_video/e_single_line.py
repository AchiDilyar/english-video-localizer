"""Strict ordered bilingual pagination; visual balance is the current policy."""
import re


def fits(text,lang,metrics):
    size=round(metrics.sizes[lang]*.8)
    return metrics.font(size).getlength(' '.join(text.split()))<=metrics.limit


def cuts(text,lang):
    result=[]
    if lang=='en':
        for match in re.finditer(r'\s+',text):
            at=match.end()
            if not text[:at].strip() or not text[at:].strip():continue
            following=re.match(r"[A-Za-z']+",text[at:]);word=following.group().lower() if following else ''
            penalty=.1 if word in {'and','that','but','while','because','how','when','as','among','until','if','which','who','than','for'} else 1.0
            if text[:at].rstrip().endswith((',',':',';','.','?','!')):penalty=0
            result.append((at,penalty))
    else:
        for at in range(1,len(text)):
            if text[at].isspace() or text[at] in '，。！？；：、）》”’':continue
            if text[at-1].isascii() and text[at].isascii() and text[at-1].isalnum() and text[at].isalnum():continue
            penalty=0 if text[at-1] in '，。！？；：、,.;:?!' else 1.3
            if text[at:].startswith(('美国','我们','他们','自己','重要','同时','仍然','因为','而且','但是','以及','如果')):penalty=min(penalty,.25)
            if text[:at].strip() and text[at:].strip():result.append((at,penalty))
    return result


def split_pair(pair,metrics,depth=0):
    if all(fits(pair[lang],lang,metrics) for lang in ['zh','en']):return [dict(pair)]
    if depth>=12:raise ValueError('SINGLE_LINE_SPLIT_LIMIT: cannot fit bilingual text safely')
    zcuts=cuts(pair['zh'],'zh');ecuts=cuts(pair['en'],'en')
    if not zcuts or not ecuts:raise ValueError('SINGLE_LINE_UNBREAKABLE: cannot split both languages without dropping text')
    best=None
    for zi,zp in zcuts:
        z=[pair['zh'][:zi],pair['zh'][zi:]];zw=[metrics.measure(v,'zh')/metrics.limit for v in z]
        for ei,ep in ecuts:
            e=[pair['en'][:ei],pair['en'][ei:]];ew=[metrics.measure(v,'en')/metrics.limit for v in e]
            overflow=sum(max(0,w*.8-1)**2 for w in zw+ew)
            imbalance=abs(zw[0]-ew[0])+abs(zw[1]-ew[1])
            cost=overflow*1000+imbalance*3+abs(zw[0]-zw[1])+abs(ew[0]-ew[1])+zp+ep
            candidate=(cost,zi,ei)
            if best is None or candidate<best:best=candidate
    _,zi,ei=best
    left={'zh':pair['zh'][:zi],'en':pair['en'][:ei]};right={'zh':pair['zh'][zi:],'en':pair['en'][ei:]}
    result=split_pair(left,metrics,depth+1)+split_pair(right,metrics,depth+1)
    if any(''.join(p[lang] for p in result)!=pair[lang] for lang in ['zh','en']):raise AssertionError('Strict pagination changed text')
    return result
