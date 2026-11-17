"""Apply existing node deltas without inventing shared state fields."""
from contracts import GraphState


def resolve_stage_nodes(names):
    from importlib import import_module
    from graph.registry import load_node_modes
    from graph.incremental import apply_incremental_proxy
    modes=load_node_modes()
    selected={name:getattr(import_module(f"{'mocks' if modes[name]=='mock' else 'nodes'}.{name}"),name) for name in names}
    wrapped=apply_incremental_proxy(selected)
    return tuple(wrapped[name] for name in names)


def run_nodes(state,nodes):
    working=state.model_copy(deep=True);combined={}
    for node in nodes:
        delta=node(working)
        if not isinstance(delta,dict) or set(delta)-set(GraphState.model_fields):
            raise ValueError('BCDE stage returned an invalid GraphState delta')
        working=GraphState.model_validate({**working.model_dump(),**delta});combined.update(delta)
    return combined
