"""Four high-level LangGraph stages, independent of F's basic-node registry."""
from dataclasses import dataclass
from contracts import GraphState
from langgraph.graph import StateGraph,START,END
from .b_source import run_b
from .c_content import run_c
from .d_voice import run_d
from .e_delivery import run_e


@dataclass
class StageServices:
    # None selects real existing nodes. Explicit adapters support validated
    # caches/tests; their provenance must be reported, never called fresh runs.
    b_nodes: tuple|None=None
    c_nodes: tuple|None=None
    d_nodes: tuple|None=None
    e_nodes: tuple|None=None


def build_bcde_graph(services=None):
    services=services or StageServices();graph=StateGraph(GraphState)
    for name,fn,nodes in [('b_source',run_b,services.b_nodes),('c_content',run_c,services.c_nodes),
                          ('d_voice',run_d,services.d_nodes),('e_delivery',run_e,services.e_nodes)]:
        def invoke(state,fn=fn,nodes=nodes):return fn(state,nodes)
        graph.add_node(name,invoke)
    graph.add_edge(START,'b_source');graph.add_edge('b_source','c_content')
    graph.add_edge('c_content','d_voice');graph.add_edge('d_voice','e_delivery');graph.add_edge('e_delivery',END)
    return graph.compile()
