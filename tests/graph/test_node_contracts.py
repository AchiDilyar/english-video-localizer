"""基础版节点与主图的接口契约检查。

- 签名检查：基础版节点主函数只接受一个参数。
- 产物名检查：基础版节点中直接调用的 write_artifact / artifact_path /
  read_artifact 的第一个参数若是字符串字面量，必须在 ARTIFACT_SPECS 中；
  非字面量（变量、f-string 等）报告给人工检查，不失败。
  别名导入与 getattr 动态调用不在检查范围，靠运行时 KeyError 与人工审查。
- GraphState 契约：cli.py 的初始构造、input_video 字段、导出名。

不 import、不调用节点，只用 AST 读源码；不需要 API key。
"""
from __future__ import annotations

import ast
import inspect
from importlib import import_module
from pathlib import Path

import pytest

from contracts import GraphState
from graph.incremental import INCREMENTAL_NODE_NAMES
from graph.registry import NODE_NAMES
from utils.artifacts import ARTIFACT_SPECS
import warnings

_NODES_DIR = Path(__file__).resolve().parents[2] / "project" / "nodes"
_INCREMENTAL = set(INCREMENTAL_NODE_NAMES)
_BASE_NODE_NAMES = tuple(n for n in NODE_NAMES if n not in _INCREMENTAL)

_ARTIFACT_FUNCS = frozenset({"write_artifact", "artifact_path", "read_artifact"})


def _node_files(name: str) -> list[Path]:
    path = _NODES_DIR / name
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.py"))
    return []


def _artifact_calls(tree: ast.AST) -> list[tuple[int, str, ast.AST]]:
    """返回 (行号, 函数名, 第一个参数) 列表，只识别直接调用。"""
    calls: list[tuple[int, str, ast.AST]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name) and func.id in _ARTIFACT_FUNCS:
            name = func.id
        elif isinstance(func, ast.Attribute) and func.attr in _ARTIFACT_FUNCS:
            name = func.attr
        if name is not None and node.args:
            calls.append((node.lineno, name, node.args[0]))
    return calls


def _string_literal(arg: ast.AST) -> str | None:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


# ---------------------------------------------------------------------------
# 签名
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _BASE_NODE_NAMES)
def test_base_node_signature(name: str) -> None:
    """基础版节点主函数只接受一个参数。

    会 import 真实节点；若节点 import 时有副作用（加载模型、读配置失败），
    测试会失败，这本身也是接口信号。
    """
    module = import_module(f"nodes.{name}")
    func = getattr(module, name)
    params = list(inspect.signature(func).parameters.values())
    assert len(params) == 1, (
        f"{name} 应只接受一个参数 state，实际 {len(params)}: "
        f"{[p.name for p in params]}"
    )


# ---------------------------------------------------------------------------
# 产物名
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _BASE_NODE_NAMES)
def test_base_node_artifact_names_registered(name: str) -> None:
    """基础版节点直接调用的产物函数，字面量名称必须已登记。

    非字面量参数无法静态判断，打印给人工检查，不失败。
    不检查 Pydantic 校验是否通过、类型是否匹配、已登记名称的语义。
    """
    unregistered: list[str] = []
    unresolved: list[str] = []

    for path in _node_files(name):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, func_name, arg in _artifact_calls(tree):
            literal = _string_literal(arg)
            if literal is None:
                unresolved.append(f"{path}:{lineno} {func_name}(...)")
            elif literal not in ARTIFACT_SPECS:
                unregistered.append(f"{path}:{lineno} {func_name}({literal!r})")

    assert not unregistered, (
        f"{name} 调用了未登记的产物名: {unregistered}；"
        f"产物登记见 utils/artifacts.py 的 ARTIFACT_SPECS"
    )
    if unresolved:
        warnings.warn(
            f"{name} 的 write_artifact/artifact_path/read_artifact 参数非字面量，"
            f"无法静态判断，需人工检查：\n  " + "\n  ".join(unresolved),
            UserWarning,
            stacklevel=2,
        )


# ---------------------------------------------------------------------------
# GraphState 契约（cli.py 的初始构造）
# ---------------------------------------------------------------------------


def test_graph_state_constructible_with_only_input_video() -> None:
    """cli.py 只传 input_video 构造 GraphState，其他字段必须可选。"""
    state = GraphState(input_video="input.mp4")
    assert state.input_video == "input.mp4"


def test_input_video_field_type_and_default() -> None:
    """input_video 必须可选、默认 None；cli.py 依赖文件名语义。"""
    field = GraphState.model_fields["input_video"]
    assert field.default is None, (
        f"input_video 默认值应为 None，实际 {field.default!r}"
    )
    state = GraphState(input_video="input.mp4")
    assert isinstance(state.input_video, str)
