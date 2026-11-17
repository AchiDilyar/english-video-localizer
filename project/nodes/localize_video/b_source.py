"""B: immutable source understanding and original-sound assets."""
from .common import run_nodes,resolve_stage_nodes


def run_b(state,nodes=None):
    if nodes is None:
        nodes=resolve_stage_nodes(('probe_input','asr_diarize'))
    return run_nodes(state,nodes)


def select_source(*args,**kwargs):
    from nodes.asr_diarize.pipeline.sources import select_source as select
    return select(*args,**kwargs)


def acquire_source(*args,**kwargs):
    from nodes.asr_diarize.pipeline.sources import acquire
    return acquire(*args,**kwargs)


def separate_background(*args,**kwargs):
    from nodes.background_audio import separate
    return separate(*args,**kwargs)


def restore_nonverbal(*args,**kwargs):
    from nodes.nonverbal_events import restore_nonverbal as restore
    return restore(*args,**kwargs)


def build_event_features(*args,**kwargs):
    from nodes.nonverbal_events import features
    return features(*args,**kwargs)


def classify_events(*args,**kwargs):
    from nodes.nonverbal_events import classify
    return classify(*args,**kwargs)


def select_nonverbal_regions(*args,**kwargs):
    from nodes.nonverbal_events import guarded_intervals
    return guarded_intervals(*args,**kwargs)


def publish_environment(source_video,environment,output,evidence):
    import json,shutil
    from pathlib import Path
    from nodes.background_audio import digest
    if (evidence.get('source_sha256'),evidence.get('environment_sha256'))!=(digest(source_video),digest(environment)):
        raise ValueError('B environment evidence does not match source/bed')
    output=Path(output)
    if Path(environment).resolve()!=output.resolve():shutil.copy2(environment,output)
    output.with_suffix('.source.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return output
