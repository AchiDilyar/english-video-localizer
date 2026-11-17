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

def _reachable_from(start, edges):
    """从 start 沿 WORKFLOW_EDGES 正向遍历，返回可达节点集合（含 start）。

    WORKFLOW_EDGES 中多前驱边以 tuple 表示，这里展开为单边。
    """
    adj: dict[str, set[str]] = {}
    for source, target in edges:
        for s in (source if isinstance(source, tuple) else (source,)):
            adj.setdefault(s, set()).add(target)
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in adj.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen

def _expand_edges(edges):
    """把 WORKFLOW_EDGES 展开成 LangGraph 内部边集合。"""
    sources, targets = set(), set()
    for source, target in edges:
        for s in (source if isinstance(source, tuple) else (source,)):
            sources.add(s)
        targets.add(target)
    first = sources - targets
    last = targets - sources
    assert len(first) == 1, f"首节点不唯一: {first}"
    assert len(last) == 1, f"末节点不唯一: {last}"
    result = {("__start__", first.pop())}
    for source, target in edges:
        if isinstance(source, tuple):
            for s in source:
                result.add((s, target))
        else:
            result.add((source, target))
    result.add((last.pop(), "__end__"))
    return result


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
    """workflow.md 第 3 节：所有节点全部进入图。"""
    _install_fake_nodes(monkeypatch, [])
    compiled = builder.build_graph()

    node_ids = set(compiled.get_graph().nodes.keys())
    missing = set(registry.NODE_NAMES) - node_ids
    assert not missing, f"图中缺少节点: {sorted(missing)}"


def test_edges_match_workflow(monkeypatch):
    """验证 LangGraph 展开后的边与 WORKFLOW_EDGES 语义一致。

    expected 从 builder.WORKFLOW_EDGES 派生，改图时无需手改本测试；
    本测试只保证 LangGraph 对多前驱 tuple 的展开与 WORKFLOW_EDGES 一致。
    """
    _install_fake_nodes(monkeypatch, [])
    compiled = builder.build_graph()
    actual = {(e.source, e.target) for e in compiled.get_graph().edges}
    expected = _expand_edges(builder.WORKFLOW_EDGES)
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
    assert calls.index('subtitle_cover') > calls.index('tts_align')


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
    """architecture.md 第 8 节：节点异常直接抛出，图终止，下游不执行。

    失败节点为测试输入；下游集合从 WORKFLOW_EDGES 派生，不写死下游节点名。
    """
    fail_at = "translate_blocks"
    calls: list[str] = []
    _install_fake_nodes(monkeypatch, calls, fail_at=fail_at)

    with pytest.raises(RuntimeError, match=fail_at):
        builder.build_graph().invoke(_initial_state())

    assert fail_at in calls, f"失败节点应被执行；实际: {calls}"

    downstream = _reachable_from(fail_at, builder.WORKFLOW_EDGES) - {fail_at}
    assert downstream, f"{fail_at} 没有下游节点，测试无意义"

    executed_downstream = set(calls) & downstream
    assert not executed_downstream, (
        f"失败后不应执行下游；实际下游调用: {sorted(executed_downstream)}；"
        f"完整序列: {calls}"
    )


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
