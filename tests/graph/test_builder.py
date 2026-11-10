from contracts import GraphState
from graph import build_graph
from graph import builder, registry


def test_workflow_joins_run_each_node_once(monkeypatch):
    calls = []

    def node(name):
        def execute(state):
            assert isinstance(state, GraphState)
            calls.append(name)
            return {}

        return execute

    monkeypatch.setattr(builder, "resolve_nodes", lambda: {n: node(n) for n in registry.NODE_NAMES})
    result = build_graph().invoke(GraphState(input_video="input.mp4"))
    assert result["input_video"] == "input.mp4"
    assert set(calls) == set(registry.NODE_NAMES)
    assert len(calls) == len(registry.NODE_NAMES)
    assert calls.index("subtitle_cover") > calls.index("edit_assets")
    assert calls.index("compose_video") > max(calls.index("tts_align"), calls.index("subtitle_cover"))
    assert calls[-2:] == ["collect_manifest", "package_zip"]


def test_integration_stop_does_not_execute_downstream(monkeypatch):
    calls = []

    def node(name):
        def execute(state):
            calls.append(name)
            return {}

        return execute

    monkeypatch.setattr(builder, "resolve_nodes", lambda: {n: node(n) for n in registry.NODE_NAMES})
    build_graph(interrupt_after=["review_blocks"]).invoke(GraphState(input_video="input.mp4"))
    assert calls == list(registry.NODE_NAMES[:5])


def test_node_failure_stops_before_downstream(monkeypatch):
    import pytest

    calls = []

    def node(name):
        def execute(state):
            calls.append(name)
            if name == "translate_blocks":
                raise ValueError("test translation failure")
            return {}

        return execute

    monkeypatch.setattr(builder, "resolve_nodes", lambda: {n: node(n) for n in registry.NODE_NAMES})
    with pytest.raises(ValueError, match="test translation failure"):
        build_graph().invoke(GraphState(input_video="input.mp4"))
    assert calls == list(registry.NODE_NAMES[:4])
