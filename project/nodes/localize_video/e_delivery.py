"""Legacy helper imports only; execution is scheduled exclusively by graph/."""
from .common import run_nodes, resolve_stage_nodes


def mix_prepared_environment(state):
    from nodes.mix_background import mix_background
    return mix_background(state)


def run_e(state, nodes=None):
    if nodes is None:
        nodes = resolve_stage_nodes(('subtitle_cover', 'mix_background', 'compose_video'))
    return run_nodes(state, nodes)
