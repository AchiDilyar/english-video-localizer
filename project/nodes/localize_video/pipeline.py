"""Deprecated import compatibility; graph topology belongs exclusively to graph/."""
import warnings


def build_bcde_graph(services=None):
    if services is not None:
        raise ValueError("Stage overrides are retired; use graph.registry in tests")
    warnings.warn("Use graph.build_graph / run-input; the separate BCDE graph is retired",
                  DeprecationWarning, stacklevel=2)
    from graph import build_graph
    return build_graph()
