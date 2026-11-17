"""验证 graph.incremental 的代理行为与图级别异常隔离。

对应 architecture.md 8.2：增量节点异常由 graph/ 层统一代理捕获，记录
warning、返回空增量、图继续执行；基础版节点仍按 8.1 抛出。

单元测试部分不依赖真实节点；图级别测试通过 patch 常量走真实
builder.build_graph() 路径，不修改生产代码。测试约定：增量节点分支从
probe_input 之后开始、在 compose_video 之前汇入，与基础版链并行。
"""

from __future__ import annotations

import logging
from types import ModuleType

import pytest

import graph.incremental as incremental_mod
from contracts import GraphState
from graph import builder, registry


# ---------------------------------------------------------------------------
# A. 代理单元测试，不涉及图
# ---------------------------------------------------------------------------


def test_wrapper_passes_through_normal_return():
    """正常返回的增量字典原样透传。"""
    def node(state):
        return {"foo": "bar"}

    wrapped = incremental_mod.wrap_incremental("node", node)
    assert wrapped(None) == {"foo": "bar"}


def test_wrapper_swallows_exception_and_logs_warning(caplog):
    """增量节点抛 Exception 时返回空增量，并记录一条带栈的 warning。"""
    def node(state):
        raise RuntimeError("boom")

    wrapped = incremental_mod.wrap_incremental("node", node)
    with caplog.at_level(logging.WARNING):
        result = wrapped(None)

    assert result == {}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "node" in message
    assert "增量节点" in message
    assert warnings[0].exc_info is not None


def test_wrapper_does_not_catch_base_exception():
    """非 Exception 的 BaseException 子类继续向上抛出。"""
    class MyBaseException(BaseException):
        pass

    def node(state):
        raise MyBaseException("nope")

    wrapped = incremental_mod.wrap_incremental("node", node)
    with pytest.raises(MyBaseException):
        wrapped(None)


def test_apply_incremental_proxy_only_wraps_incremental(monkeypatch):
    """apply_incremental_proxy 只包装 INCREMENTAL_NODE_NAMES 中的节点。"""
    monkeypatch.setattr(incremental_mod, "INCREMENTAL_NODE_NAMES", frozenset({"a"}))

    def a(state):
        return {}

    def b(state):
        return {}

    result = incremental_mod.apply_incremental_proxy({"a": a, "b": b})
    assert result["a"] is not a
    assert getattr(result["a"], "__wrapped__") is a
    assert result["b"] is b


def test_apply_incremental_proxy_empty_set_keeps_identity(monkeypatch):
    """INCREMENTAL_NODE_NAMES 为空时，返回映射的值与原函数同一对象。"""
    monkeypatch.setattr(incremental_mod, "INCREMENTAL_NODE_NAMES", frozenset())

    def a(state):
        return {}

    def b(state):
        return {}

    result = incremental_mod.apply_incremental_proxy({"a": a, "b": b})
    assert result["a"] is a
    assert result["b"] is b


def test_wrapper_preserves_metadata():
    """包装后保留 __name__、__doc__ 与 __wrapped__。"""
    def my_node(state):
        """docstring"""
        return {}

    wrapped = incremental_mod.wrap_incremental("my_node", my_node)
    assert wrapped.__name__ == "my_node"
    assert wrapped.__doc__ == "docstring"
    assert wrapped.__wrapped__ is my_node


def test_wrapper_swallows_oserror(caplog):
    """用 OSError 模拟写盘失败，增量节点包装后仍返回空增量。"""
    def node(state):
        raise OSError("disk full")

    wrapped = incremental_mod.wrap_incremental("node", node)
    with caplog.at_level(logging.WARNING):
        assert wrapped(None) == {}
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# B. 图级别增量隔离测试：patch 常量走真实 build_graph
# ---------------------------------------------------------------------------

ORIGINAL_NODE_NAMES = (
    "probe_input",
    "asr_diarize",
    "b_environment",
    "build_blocks",
    "translate_blocks",
    "review_blocks",
    "repair_blocks",
    "tts_align",
    "subtitle_cover",
    "mix_background",
    "compose_video",
)

EXTENDED_NODE_NAMES = ORIGINAL_NODE_NAMES + ("incremental_x",)

# 展开多前驱等待边，便于断言；语义与 builder 原 WORKFLOW_EDGES 一致。
EXTENDED_EDGES = (
    ("probe_input", "asr_diarize"),
    ("asr_diarize", "b_environment"),
    ("asr_diarize", "build_blocks"),
    ("build_blocks", "translate_blocks"),
    ("translate_blocks", "review_blocks"),
    ("review_blocks", "repair_blocks"),
    ("repair_blocks", "tts_align"),
    ("tts_align", "subtitle_cover"),
    (("subtitle_cover", "b_environment"), "mix_background"),
    ("review_blocks", "incremental_x"),
    (("mix_background", "incremental_x"), "compose_video"),
)


@pytest.fixture
def incremental_graph(monkeypatch):
    """构造“基础版链 + review_blocks 后并行增量叶子”的图。

    增量节点从 review_blocks 后分叉、汇入 compose_video，不成为基础版
    节点的必需前置；不修改 builder.py，仅 patch 常量。
    """
    calls: list[str] = []
    behaviors: dict[str, object] = {}

    def importer(full_name):
        short = full_name.rsplit(".", 1)[-1]
        module = ModuleType(full_name)

        def execute(state, _short=short):
            calls.append(_short)
            behavior = behaviors.get(_short)
            if behavior is not None:
                return behavior(state)
            return {}

        setattr(module, short, execute)
        return module

    monkeypatch.setattr(registry, "NODE_NAMES", EXTENDED_NODE_NAMES)
    monkeypatch.setattr(builder, "NODE_NAMES", EXTENDED_NODE_NAMES)
    monkeypatch.setattr(builder, "WORKFLOW_EDGES", EXTENDED_EDGES)
    monkeypatch.setattr(
        registry, "INCREMENTAL_NODE_NAMES", frozenset({"incremental_x"})
    )
    monkeypatch.setattr(
        incremental_mod, "INCREMENTAL_NODE_NAMES", frozenset({"incremental_x"})
    )
    monkeypatch.setattr(registry, "load_config", lambda _: {})
    monkeypatch.setattr(registry, "import_module", importer)

    yield calls, behaviors


def test_incremental_failure_does_not_stop_graph(incremental_graph, caplog):
    """增量节点抛异常时返回空增量，基础版链与 compose_video 继续执行。"""
    calls, behaviors = incremental_graph

    def fail(_state):
        raise RuntimeError("incremental failed")

    behaviors["incremental_x"] = fail

    with caplog.at_level(logging.WARNING):
        result = builder.build_graph().invoke(GraphState(input_video="input.mp4"))

    for name in ORIGINAL_NODE_NAMES:
        assert calls.count(name) == 1, f"{name} 应执行一次；实际: {calls}"
    assert calls.count("incremental_x") == 1
    assert calls.index("compose_video") > calls.index("incremental_x"), (
        f"compose_video 应在 incremental_x 之后；实际: {calls}"
    )
    assert result["input_video"] == "input.mp4", "增量异常不应改变基础版字段"

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "incremental_x" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert warnings[0].exc_info is not None


def test_incremental_success_merges_increment(incremental_graph):
    """增量节点正常返回时，增量合并进 State，compose_video 仍执行。"""
    calls, behaviors = incremental_graph

    def succeed(_state):
        return {"input_video": "incremental.mp4"}

    behaviors["incremental_x"] = succeed

    result = builder.build_graph().invoke(GraphState(input_video="input.mp4"))

    for name in ORIGINAL_NODE_NAMES:
        assert calls.count(name) == 1, f"{name} 应执行一次；实际: {calls}"
    assert calls.index("compose_video") > calls.index("incremental_x")
    assert result["input_video"] == "incremental.mp4", "增量应合并进 State"