"""B entry point: probe_input(state: GraphState) -> dict."""
from contracts import GraphState


def probe_input(state: GraphState) -> dict:
    from .node import probe_input as execute

    return execute(state)


__all__ = ["probe_input"]
