"""Connect the v1.3 basic workflow; no repair loops or business processing."""
from collections.abc import Sequence

from contracts import GraphState
from langgraph.graph import END, START, StateGraph

from .registry import NODE_NAMES, resolve_nodes


def build_graph(*, interrupt_after: Sequence[str] | None = None):
    """Build the team graph; optional stop points support staged integration.

    Stops do not enable checkpoints/resume and do not indicate final delivery.
    Real/mock switching remains exclusively in registry.py and mock.toml.
    """
    stops = list(interrupt_after or [])
    if set(stops) - set(NODE_NAMES):
        raise ValueError("Unknown integration stop node")
    graph = StateGraph(GraphState)
    for name, function in resolve_nodes().items():
        graph.add_node(name, function)
    graph.add_edge(START, "probe_input")
    for before, after in zip(NODE_NAMES[:4], NODE_NAMES[1:5]):
        graph.add_edge(before, after)
    graph.add_edge("review_blocks", "tts_align")
    graph.add_edge("review_blocks", "edit_assets")
    graph.add_edge(["review_blocks", "edit_assets"], "subtitle_cover")
    graph.add_edge(["tts_align", "subtitle_cover"], "compose_video")
    graph.add_edge("compose_video", "collect_manifest")
    graph.add_edge("collect_manifest", "package_zip")
    graph.add_edge("package_zip", END)
    return graph.compile(interrupt_after=stops or None)
