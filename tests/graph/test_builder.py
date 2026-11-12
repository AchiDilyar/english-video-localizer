"""验证 graph.build_graph 的节点注册、边集合与执行语义。

对应 workflow.md 第 3 节（节点清单）、第 4 节（依赖与并行）、
architecture.md 第 3 节（节点入参 GraphState、增量合并）、第 8 节（失败即抛出）。

用真实 StateGraph + fake 节点直接观察 LangGraph 行为，
不 mock StateGraph 内部结构，避免绑定框架版本内部表示。
"""

from __future__ import annotations

import pytest

import graph
from contracts import GraphState
from graph import builder, registry


def _install_fake_nodes(monkeypatch, calls, fail_at=None):
    def make(name):
        def execute(state):
            calls.append(name)
            if name == fail_at:
                raise RuntimeError(f"node {name} failed")
            return {}

        return execute

    fake = {name: make(name) for name in registry.NODE_NAMES}
    monkeypatch.setattr(builder, "resolve_nodes", lambda: fake)
    return fake


def _initial_state():
    return GraphState(input_video="input.mp4")


def test_all_nodes_registered(monkeypatch):
    """workflow.md 第 3 节：8 个节点全部进入图。"""
    _install_fake_nodes(monkeypatch, [])
    compiled = builder.build_graph()

    node_ids = set(compiled.get_graph().nodes.keys())
    missing = set(registry.NODE_NAMES) - node_ids
    assert not missing, f"图中缺少节点: {sorted(missing)}"


def test_edges_match_workflow(monkeypatch):
    """workflow.md 第 4 节：边集合与图定义逐条一致。

    多前驱等待边在 LangGraph 内部展开为多条单前驱边，
    因此断言展开后的边集合。版本升级导致表示变化时本测试失败，
    是提醒检查语义而非静默容忍。
    """
    _install_fake_nodes(monkeypatch, [])
    compiled = builder.build_graph()

    actual = {(e.source, e.target) for e in compiled.get_graph().edges}
    expected = {
        ("__start__", "probe_input"),
        ("probe_input", "asr_diarize"),
        ("asr_diarize", "build_blocks"),
        ("build_blocks", "translate_blocks"),
        ("translate_blocks", "review_blocks"),
        ("review_blocks", "tts_align"),
        ("review_blocks", "subtitle_cover"),
        ("tts_align", "compose_video"),
        ("subtitle_cover", "compose_video"),
        ("compose_video", "__end__"),
    }
    assert actual == expected, (
        f"缺少边: {sorted(expected - actual)}；多余边: {sorted(actual - expected)}"
    )


def test_each_node_runs_exactly_once(monkeypatch):
    """汇合节点有多个前驱，但不重复触发；8 个节点各执行一次。"""
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls)

    builder.build_graph().invoke(_initial_state())

    assert len(calls) == len(registry.NODE_NAMES), (
        f"应执行 {len(registry.NODE_NAMES)} 个节点，实际序列: {calls}"
    )
    for name in registry.NODE_NAMES:
        assert calls.count(name) == 1, (
            f"{name} 执行了 {calls.count(name)} 次；实际序列: {calls}"
        )


def test_linear_prefix_in_order(monkeypatch):
    """workflow.md 第 4 节：probe_input → asr_diarize → build_blocks →
    translate_blocks → review_blocks 严格顺序。"""
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls)

    builder.build_graph().invoke(_initial_state())

    prefix = ["probe_input", "asr_diarize", "build_blocks",
              "translate_blocks", "review_blocks"]
    positions = [calls.index(n) for n in prefix]
    assert positions == sorted(positions), (
        f"线性前缀顺序错误；实际前 5 个: {calls[:5]}"
    )


def test_subtitle_cover_waits_for_review(monkeypatch):
    """workflow.md 第 4 节：subtitle_cover 等待 review_blocks。"""
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls)

    builder.build_graph().invoke(_initial_state())

    assert calls.index("subtitle_cover") > calls.index("review_blocks"), (
        f"subtitle_cover 应在 review_blocks 之后；实际: {calls}"
    )


def test_compose_video_waits_for_tts_and_subtitle(monkeypatch):
    """workflow.md 第 4 节：compose_video 等待 tts_align 和 subtitle_cover。"""
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls)

    builder.build_graph().invoke(_initial_state())

    compose = calls.index("compose_video")
    assert compose > calls.index("tts_align")
    assert compose > calls.index("subtitle_cover")


def test_compose_video_is_last_business_node(monkeypatch):
    """workflow.md 第 4 节：compose_video 是最后一个业务节点，完成后进入 END。"""
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls)

    builder.build_graph().invoke(_initial_state())

    assert calls[-1] == "compose_video", (
        f"compose_video 应为最后执行的业务节点；实际尾段: {calls[-3:]}"
    )


def test_nodes_receive_graph_state_and_increment_merges(monkeypatch):
    """architecture.md 第 3 节：入参为 GraphState，返回增量合并进 State。"""
    seen: list[type] = []

    def make(name):
        def execute(state):
            seen.append(type(state))
            if name == "subtitle_cover":
                return {"input_video": "rewritten.mp4"}
            return {}

        return execute

    monkeypatch.setattr(
        builder, "resolve_nodes",
        lambda: {n: make(n) for n in registry.NODE_NAMES},
    )

    result = builder.build_graph().invoke(_initial_state())

    assert all(t is GraphState for t in seen), (
        f"节点入参应为 GraphState；实际类型: {set(seen)}"
    )
    assert result["input_video"] == "rewritten.mp4"


def test_node_failure_stops_downstream(monkeypatch):
    """architecture.md 第 8 节：节点异常直接抛出，图终止，下游不执行。"""
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls, fail_at="translate_blocks")

    with pytest.raises(RuntimeError, match="translate_blocks"):
        builder.build_graph().invoke(_initial_state())

    assert "review_blocks" not in calls, f"失败后不应执行下游: {calls}"
    assert calls[-1] == "translate_blocks"


def test_resolve_nodes_must_cover_all_names(monkeypatch):
    """build_graph 应拒绝不完整节点集合，防止静默漏节点。"""
    fake = {name: (lambda state: {}) for name in registry.NODE_NAMES}
    fake.pop("compose_video")
    monkeypatch.setattr(builder, "resolve_nodes", lambda: fake)

    with pytest.raises(ValueError, match="compose_video"):
        builder.build_graph()


def test_resolve_nodes_rejects_unknown(monkeypatch):
    """build_graph 应拒绝 NODE_NAMES 之外的节点。"""
    fake = {name: (lambda state: {}) for name in registry.NODE_NAMES}
    fake["unexpected_node"] = lambda state: {}
    monkeypatch.setattr(builder, "resolve_nodes", lambda: fake)

    with pytest.raises(ValueError, match="unexpected_node"):
        builder.build_graph()


def test_graph_package_exports_only_build_graph():
    """architecture.md 2.3：graph 对外只暴露 build_graph。"""
    assert graph.__all__ == ["build_graph"]
    assert callable(graph.build_graph)