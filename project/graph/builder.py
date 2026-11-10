"""Connect the v1.3 basic workflow; no repair loops or business processing."""
from contracts import GraphState
from langgraph.graph import END, START, StateGraph

from .registry import NODE_NAMES, resolve_nodes


def build_graph():
    """Build and compile the basic workflow graph."""
    nodes = resolve_nodes()
    missing = set(NODE_NAMES) - set(nodes)
    extra = set(nodes) - set(NODE_NAMES)
    if missing or extra:
        raise ValueError(
            f"Resolved nodes mismatch NODE_NAMES: "
            f"missing {sorted(missing)}, extra {sorted(extra)}"
        )
    graph = StateGraph(GraphState)
    for name, function in nodes.items():
        graph.add_node(name, function)
    graph.add_edge(START, "probe_input")
    graph.add_edge("probe_input", "asr_diarize")
    graph.add_edge("asr_diarize", "build_blocks")
    graph.add_edge("build_blocks", "translate_blocks")
    graph.add_edge("translate_blocks", "review_blocks")
    graph.add_edge("review_blocks", "tts_align")
    graph.add_edge("review_blocks", "edit_assets")
    graph.add_edge(["review_blocks", "edit_assets"], "subtitle_cover")
    graph.add_edge(["tts_align", "subtitle_cover"], "compose_video")
    graph.add_edge("compose_video", "collect_manifest")
    graph.add_edge("collect_manifest", "package_zip")
    graph.add_edge("package_zip", END)
    return graph.compile()