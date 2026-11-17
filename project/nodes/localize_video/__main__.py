"""Reuse the standard CLI with the optional high-level BCDE graph."""
from cli import main
from .pipeline import build_bcde_graph

if __name__=='__main__':
    raise SystemExit(main(graph_factory=build_bcde_graph))
