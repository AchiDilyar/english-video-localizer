"""BCDE integration facade; existing F node imports remain compatible."""
from contracts import GraphState

def build_bcde_graph(services=None):
    from .pipeline import build_bcde_graph as build
    return build(services)


def localize_video(state: GraphState) -> dict:
    result=GraphState.model_validate(build_bcde_graph().invoke(state))
    before=state.model_dump();after=result.model_dump()
    return {key:value for key,value in after.items() if value!=before[key]}
