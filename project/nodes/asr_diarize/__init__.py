"""B entry point: asr_diarize(state: GraphState) -> dict."""
from contracts import GraphState


def asr_diarize(state: GraphState) -> dict:
    from .node import asr_diarize as execute

    return execute(state)


__all__ = ["asr_diarize"]
