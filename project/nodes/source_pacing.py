"""Keep model rate neutral; return short measurements for semantic text repair."""


def prepare_paced_audio(group,text,voice,plan,synthesize,duration,cache_path):
    conditioning={k:v for k,v in group.get('conditioning',{}).items() if k!='rate'}
    enabled=getattr(plan,'source_pacing',False)
    target=group['original_end_ms']-group['start_ms'];rate=1.0
    attempts=[]
    # Model rate stays neutral. Only the measured post-process tempo may vary;
    # a short result is returned to the semantic text-repair stage.
    for _ in range(1):
        actual={**conditioning,**({'rate':rate} if enabled else {})}
        # Keep legacy calls/cache keys unchanged when this policy is disabled.
        item={**group,'text':text}
        if actual:item['conditioning']=actual
        else:item.pop('conditioning',None)
        raw=cache_path(item,voice,plan)
        if not raw.exists():
            synthesize(text,voice,plan.model,plan.sample_rate,raw,**({'conditioning':actual} if actual else {}))
        ms=duration(raw);attempts.append({'rate':rate,'raw_duration_ms':ms,'raw_file':raw.name})
    if actual:group['conditioning']=actual
    group['synthesis_pacing']=attempts
    return raw,ms
