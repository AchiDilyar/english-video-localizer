"""Connect the v1.4 basic workflow; no repair loops or business processing."""
from contracts import GraphState
from langgraph.graph import END, START, StateGraph

from .registry import NODE_NAMES, resolve_nodes

# Business edges shared by the graph and configuration validation.
WORKFLOW_EDGES = (
    ("probe_input", "asr_diarize"),
    ("asr_diarize", "build_blocks"),
    ("build_blocks", "translate_blocks"),
    ("translate_blocks", "review_blocks"),
    ("review_blocks", "tts_align"),
    ("review_blocks", "subtitle_cover"),
    (("tts_align", "subtitle_cover"), "compose_video"),
)


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
    for source, target in WORKFLOW_EDGES:
        graph.add_edge(list(source) if isinstance(source, tuple) else source, target)
    graph.add_edge("compose_video", END)
    return graph.compile()