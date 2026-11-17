"""D: source-voice synthesis, duration measurement and bounded fitting."""
from .common import run_nodes,resolve_stage_nodes


def run_d(state,nodes=None):
    if nodes is None:
        nodes=resolve_stage_nodes(('tts_align',))
    return run_nodes(state,nodes)
