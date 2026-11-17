"""验证 mocks/ 最小骨架的完整性。

事实源：workflow.md 第 3 节节点清单（经 graph.registry.NODE_NAMES 提供）。
本测试只验证：模块存在、函数同名、可调用、第一个位置参数名为 state、
mock.toml 键集合覆盖全部节点。
不验证业务字段、不验证落盘、不依赖 GraphState 字段。

EXPECTED_NODES 直接取自 graph.registry.NODE_NAMES，不再硬编码节点清单；
mocks/ 下多出的模块只产生 UserWarning，不判失败；下划线开头的内部辅助模块
（如 _video.py）不计入节点清单比对。
"""

from __future__ import annotations

import importlib
import inspect
import warnings
from pathlib import Path

import mocks as mocks_pkg
import pytest
from graph.registry import NODE_NAMES as EXPECTED_NODES

MOCKS_DIR = Path(mocks_pkg.__path__[0])


def _mock_module_names() -> list[str]:
    """节点 mock 模块；下划线开头的是内部辅助模块，不参与节点清单比对。"""
    return sorted(
        p.stem
        for p in MOCKS_DIR.glob("*.py")
        if p.stem != "__init__" and not p.stem.startswith("_")
    )


def test_mocks_dir_exists() -> None:
    assert MOCKS_DIR.is_dir(), f"mocks 目录不存在: {MOCKS_DIR}"


def test_mock_modules_cover_all_nodes() -> None:
    """节点缺少 mock 模块直接失败；多余模块只提示，不影响运行。"""
    found = set(_mock_module_names())
    expected = set(EXPECTED_NODES)
    missing = expected - found
    extra = found - expected
    assert not missing, f"缺少 mock 模块: {sorted(missing)}"
    if extra:
        warnings.warn(
            f"mocks/ 下存在未登记的模块: {sorted(extra)}",
            UserWarning,
            stacklevel=2,
        )


@pytest.mark.parametrize("node_name", EXPECTED_NODES)
def test_mock_module_defines_same_name_function(node_name: str) -> None:
    module = importlib.import_module(f"mocks.{node_name}")
    assert hasattr(module, node_name), (
        f"mocks.{node_name} 未导出名为 {node_name} 的节点函数"
    )
    assert callable(getattr(module, node_name)), (
        f"mocks.{node_name}.{node_name} 不可调用"
    )


@pytest.mark.parametrize("node_name", EXPECTED_NODES)
def test_mock_function_accepts_state(node_name: str) -> None:
    module = importlib.import_module(f"mocks.{node_name}")
    fn = getattr(module, node_name)
    params = list(inspect.signature(fn).parameters.values())
    positional = [
        p for p in params
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    assert positional, f"mocks.{node_name}.{node_name} 不接受位置参数"
    assert positional[0].name == "state", (
        f"mocks.{node_name}.{node_name} 第一个参数应命名为 state，"
        f"实际为 {positional[0].name}"
    )


def test_mock_toml_lists_all_nodes() -> None:
    """config/mock.toml 必须覆盖全部节点，每个开关均为布尔值。"""
    from utils.config import load_config

    cfg = load_config("mock.toml")
    assert isinstance(cfg, dict)
    expected = set(EXPECTED_NODES)
    assert set(cfg) == expected, (
        f"mock.toml 键与节点清单不一致："
        f"缺少 {sorted(expected - set(cfg))}，多余 {sorted(set(cfg) - expected)}"
    )
    assert all(isinstance(flag, bool) for flag in cfg.values())
